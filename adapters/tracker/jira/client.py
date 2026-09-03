"""Jira implementation of the tracker seam.

No Jira credentials exist for this repository (see the PR for #123), so
this adapter has never talked to a live Jira instance. It is unit-tested
against recorded/stubbed HTTP responses in
`adapters/tracker/tests/test_jira.py` and passes the same contract suite as
the GitHub adapter, but that only proves internal consistency — it does
**not** prove the request shapes below match what Jira Cloud actually
returns. Treat every endpoint here as a documented best guess, not a
verified integration, until someone runs it against a real project.

Mapping notes (the seams where "the operations this system uses" don't have
a 1:1 Jira concept):

- `Tracker.Issue.number` is `int`, matching GitHub. Jira keys issues as
  `<PROJECT>-<n>`; this adapter takes the numeric part and reconstructs the
  key as `f"{project_key}-{number}"`. It cannot address issues outside
  `project_key`.
- GitHub Projects v2 fields (`Status`, `QA-Verdict`, `Role`,
  `Requirement-ID`) are per-item, separate from the issue. Jira has no such
  layer — a project's issues carry their own status and custom fields
  directly. `board_fields`/`board_item`/`set_board_field` read and write the
  issue's own `status` and the custom fields named in `field_map`, treating
  "the board" as "this project". `Status` writes go through Jira's
  transitions API, matched by the target status's name, since Jira does not
  allow setting status directly.
- `add_to_board` — GitHub's "add an item to the project" has no clean Jira
  analogue for a plain project (every issue in the project is already on
  it). Where `board.number` is a Jira Agile board id with an active sprint,
  this adds the issue to that sprint; that is the closest behavioural match
  ("this issue is now visibly on the board"), not a literal translation.
- `list_pull_requests` — Jira Cloud has no repo-wide PR listing; it exposes
  pull requests per issue via the (undocumented, dev-tools) dev-status API.
  This adapter calls that endpoint once per issue and flattens the result.
  For a project with many issues this is O(issues) HTTP calls where the
  GitHub adapter makes one — acceptable here only because nothing in this
  repository actually wires the Jira adapter up yet.
- `trigger_workflow` — Jira does not run CI. This posts to a Jira Automation
  incoming webhook, one per logical workflow name, configured by the caller
  via `webhook_urls`. A workflow name with no configured URL raises.
"""

from __future__ import annotations

import json as jsonlib
import re
import urllib.request
from base64 import b64encode
from typing import Callable

from ..base import BoardItem, BoardRef, Comment, Issue, PullRequest, Tracker

Transport = Callable[..., "_Response"]


class _Response:
    def __init__(self, status: int, body: dict | None):
        self.status = status
        self.body = body


def _adf_text(body: str) -> dict:
    """Plain text wrapped in Atlassian Document Format, which the v3 API
    requires for issue and comment bodies."""
    return {"type": "doc", "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": body}]}]}


def _plain_text(adf: object) -> str:
    """Best-effort inverse of `_adf_text` for reading comments back — walks
    every `text` node and joins them. Good enough for the one place this
    system reads comment bodies back (dispatch.yml's retry-ceiling count),
    which only greps for a marker string."""
    if isinstance(adf, str):
        return adf
    if not isinstance(adf, dict):
        return ""
    out = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "text":
                out.append(node.get("text", ""))
            for child in node.get("content", []) or []:
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(adf)
    return "".join(out)


class JiraTracker(Tracker):
    def __init__(self, *, base_url: str, email: str, api_token: str, project_key: str,
                 field_map: dict | None = None, webhook_urls: dict | None = None,
                 transport: Transport | None = None):
        """`field_map` maps the logical board field names sync-project.py
        writes (`QA-Verdict`, `Role`, `Requirement-ID`) to
        `{"id": "customfield_XXXXX", "type": "select"|"text"}`. `Status` is
        handled separately, via transitions, and is not in `field_map`.
        `webhook_urls` maps a workflow name (e.g. `"dispatch.yml"`) to a
        Jira Automation incoming-webhook URL."""
        self._base_url = base_url.rstrip("/")
        self._auth = b64encode(f"{email}:{api_token}".encode()).decode()
        self._project_key = project_key
        self._field_map = field_map or {}
        self._webhook_urls = webhook_urls or {}
        self._transport = transport or self._default_transport

    # --- transport ------------------------------------------------------------

    def _default_transport(self, method: str, url: str, *, params=None, json=None) -> _Response:
        if params:
            from urllib.parse import urlencode
            url = f"{url}?{urlencode(params)}"
        data = jsonlib.dumps(json).encode() if json is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Basic {self._auth}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            body = jsonlib.loads(raw) if raw else None
            return _Response(resp.status, body)

    def _request(self, method: str, path: str, *, params=None, json=None):
        resp = self._transport(method, f"{self._base_url}{path}", params=params, json=json)
        return resp.body

    def _key(self, number: int) -> str:
        return f"{self._project_key}-{number}"

    def _number(self, key: str) -> int:
        m = re.search(r"-(\d+)$", key)
        return int(m.group(1)) if m else 0

    def _to_issue(self, raw: dict) -> Issue:
        """`Issue.state` is OPEN/CLOSED, the same binary every caller in
        this codebase actually branches on (see `ineligible_reason` in
        assign.py and the guard step in dispatch.yml) — not Jira's raw
        workflow status name, which has no fixed vocabulary and is exposed
        instead as the board's `Status` field (see `board_item`). It is
        derived from Jira's `statusCategory`, whose three fixed values
        (new, indeterminate, done) are the closest thing Jira has to
        GitHub's open/closed."""
        fields = raw.get("fields", {})
        category = ((fields.get("status") or {}).get("statusCategory") or {}).get("key")
        return Issue(
            number=self._number(raw["key"]),
            id=raw["id"],
            title=fields.get("summary", ""),
            body=_plain_text(fields.get("description")),
            state="CLOSED" if category == "done" else "OPEN",
            labels=tuple(fields.get("labels", []) or []),
            url=f"{self._base_url}/browse/{raw['key']}",
        )

    # --- issues -----------------------------------------------------------------

    def list_issues(self, *, state: str = "all", limit: int = 200) -> list[Issue]:
        jql = f"project = {self._project_key}"
        if state == "open":
            jql += " AND statusCategory != Done"
        raw = self._request("GET", "/rest/api/3/search", params={
            "jql": jql, "maxResults": limit,
            "fields": "summary,description,status,labels",
        })
        return [self._to_issue(i) for i in (raw or {}).get("issues", [])]

    def get_issue(self, number: int) -> Issue:
        raw = self._request("GET", f"/rest/api/3/issue/{self._key(number)}")
        return self._to_issue(raw)

    def comment(self, number: int, body: str) -> None:
        self._request("POST", f"/rest/api/3/issue/{self._key(number)}/comment",
                       json={"body": _adf_text(body)})

    def edit_labels(self, number: int, *, add: tuple[str, ...] = (),
                     remove: tuple[str, ...] = ()) -> None:
        if not add and not remove:
            return
        update = [{"add": l} for l in add] + [{"remove": l} for l in remove]
        self._request("PUT", f"/rest/api/3/issue/{self._key(number)}",
                       json={"update": {"labels": update}})

    def list_comments(self, number: int) -> list[Comment]:
        raw = self._request("GET", f"/rest/api/3/issue/{self._key(number)}/comment")
        return [Comment(body=_plain_text(c.get("body"))) for c in (raw or {}).get("comments", [])]

    # --- pull requests --------------------------------------------------------

    def list_pull_requests(self, *, state: str = "open", limit: int = 100) -> list[PullRequest]:
        prs: list[PullRequest] = []
        for issue in self.list_issues(state="all", limit=limit):
            raw = self._request("GET", "/rest/dev-status/1.0/issue/detail", params={
                "issueId": issue.id, "applicationType": "GitHub", "dataType": "pullrequest",
            })
            for detail in (raw or {}).get("detail", []):
                for pr in detail.get("pullRequests", []):
                    pr_state = (pr.get("status") or "").upper()
                    if state != "all" and pr_state != state.upper():
                        continue
                    m = re.search(r"/pull/(\d+)", pr.get("url", ""))
                    prs.append(PullRequest(
                        number=int(m.group(1)) if m else 0,
                        url=pr.get("url", ""),
                        head_ref=(pr.get("source") or {}).get("branch", ""),
                        state=pr_state,
                    ))
            if len(prs) >= limit:
                break
        return prs[:limit]

    # --- dispatch -----------------------------------------------------------------

    def trigger_workflow(self, workflow: str, inputs: dict) -> None:
        url = self._webhook_urls.get(workflow)
        if not url:
            raise KeyError(
                f"no Jira Automation webhook configured for workflow {workflow!r} "
                f"(configured: {sorted(self._webhook_urls)})")
        self._transport("POST", url, json={"workflow": workflow, **inputs})

    # --- project board (== this Jira project) ------------------------------------

    def board_fields(self, board: BoardRef) -> dict:
        out: dict = {}
        statuses = self._request("GET", f"/rest/api/3/project/{self._project_key}/statuses")
        names = {s["name"] for group in (statuses or []) for s in group.get("statuses", [])}
        out["Status"] = sorted(names)
        for name, spec in self._field_map.items():
            if spec.get("type") != "select":
                out[name] = []
                continue
            contexts = self._request("GET", f"/rest/api/3/field/{spec['id']}/context")
            options: list[str] = []
            for ctx in (contexts or {}).get("values", []):
                opts = self._request(
                    "GET", f"/rest/api/3/field/{spec['id']}/context/{ctx['id']}/option")
                options += [o["value"] for o in (opts or {}).get("values", [])]
            out[name] = options
        return out

    def _active_sprint(self, board: BoardRef) -> dict | None:
        sprints = self._request("GET", f"/rest/agile/1.0/board/{board.number}/sprint",
                                 params={"state": "active"})
        return next(iter((sprints or {}).get("values", [])), None)

    def board_item(self, board: BoardRef, issue_number: int) -> BoardItem | None:
        """A plain Jira project has no separate "is this issue on the
        board" flag the way a GitHub Projects v2 item does — any issue in
        the project matches most boards' filter already. The active sprint
        is the one place Jira tracks explicit membership, so that is what
        `add_to_board` adds to and this checks — consistent with each
        other, not a universal definition of "on the board" for every
        board configuration."""
        active = self._active_sprint(board)
        if active is None:
            return None
        on_sprint = self._request("GET", f"/rest/agile/1.0/sprint/{active['id']}/issue",
                                   params={"jql": f"key = {self._key(issue_number)}"})
        if not (on_sprint or {}).get("issues"):
            return None

        raw = self._request("GET", f"/rest/api/3/issue/{self._key(issue_number)}")
        fields = raw.get("fields", {})
        values = {"Status": (fields.get("status") or {}).get("name", "")}
        for name, spec in self._field_map.items():
            value = fields.get(spec["id"])
            if isinstance(value, dict):
                value = value.get("value")
            if value is not None:
                values[name] = value
        return BoardItem(issue_number=issue_number, field_values=values)

    def add_to_board(self, board: BoardRef, issue_number: int) -> None:
        active = self._active_sprint(board)
        if active is None:
            raise KeyError(f"board {board.number} has no active sprint to add issue "
                            f"{issue_number} to")
        self._request("POST", f"/rest/agile/1.0/sprint/{active['id']}/issue",
                       json={"issues": [self._key(issue_number)]})

    def set_board_field(self, board: BoardRef, issue_number: int, field_name: str,
                         value: str) -> None:
        if field_name == "Status":
            transitions = self._request(
                "GET", f"/rest/api/3/issue/{self._key(issue_number)}/transitions")
            match = next((t for t in (transitions or {}).get("transitions", [])
                          if t["to"]["name"] == value), None)
            if match is None:
                raise KeyError(f"no transition to status {value!r} from the issue's "
                                f"current state")
            self._request("POST", f"/rest/api/3/issue/{self._key(issue_number)}/transitions",
                           json={"transition": {"id": match["id"]}})
            return

        spec = self._field_map.get(field_name)
        if spec is None:
            raise KeyError(f"field {field_name!r} is not in field_map")
        payload = {"value": value} if spec.get("type") == "select" else value
        self._request("PUT", f"/rest/api/3/issue/{self._key(issue_number)}",
                       json={"fields": {spec["id"]: payload}})
