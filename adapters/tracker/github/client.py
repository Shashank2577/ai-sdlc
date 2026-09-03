"""GitHub implementation of the tracker seam.

This is `scripts/sync-project.py`'s `gh_json`/`graphql`/`load_board`/
`field_index`/`current_values`/`write_field`/`add_item`, `scripts/assign.py`'s
`gh`/`collect_issues`/`collect_issues_with_open_prs`/`dispatch_one`, and the
`gh` invocations in `.github/workflows/dispatch.yml`, moved behind
`adapters.tracker.base.Tracker` with no change in behaviour. Those scripts
still call `gh` directly today (this story introduces the seam; it does not
rewire them — see the PR).
"""

from __future__ import annotations

import json
import subprocess
from typing import Callable

from ..base import BoardItem, BoardRef, Comment, Issue, PullRequest, Tracker

GhRunner = Callable[[list[str]], str]


def _default_run(args: list[str]) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


class GitHubTracker(Tracker):
    def __init__(self, *, repo: str | None = None, run: GhRunner = _default_run):
        """`repo` is passed as `--repo <owner>/<name>` on every call when
        given, so this adapter is not tied to `gh`'s notion of "the repo in
        the current directory" the way the original scripts were. `run` is
        the injection seam the contract tests use to stub `gh` without a
        network or a real repository."""
        self._repo = repo
        self._run = run

    def _gh(self, args: list[str]) -> str:
        if self._repo:
            args = [*args, "--repo", self._repo]
        return self._run(args)

    def _gh_json(self, args: list[str]):
        return json.loads(self._gh(args) or "null")

    def _graphql(self, query: str, **variables) -> dict:
        args = ["api", "graphql", "-f", f"query={query}"]
        for k, v in variables.items():
            flag = "-F" if isinstance(v, int) else "-f"
            args += [flag, f"{k}={v}"]
        return self._gh_json(args)

    @staticmethod
    def _to_issue(raw: dict) -> Issue:
        return Issue(
            number=raw["number"],
            id=raw.get("id", ""),
            title=raw.get("title", ""),
            body=raw.get("body") or "",
            state=raw.get("state", ""),
            labels=tuple(l["name"] for l in raw.get("labels", [])),
            url=raw.get("url", ""),
        )

    # --- issues -------------------------------------------------------------

    def list_issues(self, *, state: str = "all", limit: int = 200) -> list[Issue]:
        raw = self._gh_json([
            "issue", "list", "--state", state, "--limit", str(limit),
            "--json", "number,title,state,labels,body,id,url",
        ]) or []
        return [self._to_issue(i) for i in raw]

    def get_issue(self, number: int) -> Issue:
        raw = self._gh_json([
            "issue", "view", str(number),
            "--json", "number,title,state,labels,body,id,url",
        ])
        return self._to_issue(raw)

    def comment(self, number: int, body: str) -> None:
        self._gh(["issue", "comment", str(number), "--body", body])

    def edit_labels(self, number: int, *, add: tuple[str, ...] = (),
                     remove: tuple[str, ...] = ()) -> None:
        args = ["issue", "edit", str(number)]
        for label in add:
            args += ["--add-label", label]
        for label in remove:
            args += ["--remove-label", label]
        if add or remove:
            self._gh(args)

    def list_comments(self, number: int) -> list[Comment]:
        raw = self._gh_json([
            "api", "--paginate", f"repos/{{owner}}/{{repo}}/issues/{number}/comments",
        ]) or []
        return [Comment(body=c.get("body", "")) for c in raw]

    # --- pull requests --------------------------------------------------------

    def list_pull_requests(self, *, state: str = "open", limit: int = 100) -> list[PullRequest]:
        raw = self._gh_json([
            "pr", "list", "--state", state, "--limit", str(limit),
            "--json", "number,url,headRefName,state",
        ]) or []
        return [PullRequest(number=p["number"], url=p.get("url", ""),
                             head_ref=p.get("headRefName", ""), state=p.get("state", ""))
                for p in raw]

    # --- dispatch ---------------------------------------------------------------

    def trigger_workflow(self, workflow: str, inputs: dict) -> None:
        args = ["workflow", "run", workflow]
        for k, v in inputs.items():
            args += ["-f", f"{k}={v}"]
        self._gh(args)

    # --- project board ----------------------------------------------------------

    _PROJECT_QUERY = """
    query($owner:String!, $number:Int!) {
      user(login:$owner) { projectV2(number:$number) {
        id
        fields(first:40) { nodes {
          ... on ProjectV2Field { id name }
          ... on ProjectV2SingleSelectField { id name options { id name } }
        }}
        items(first:100) { nodes {
          id
          content { ... on Issue { number state } }
          fieldValues(first:40) { nodes {
            ... on ProjectV2ItemFieldTextValue        { text  field { ... on ProjectV2FieldCommon { name }}}
            ... on ProjectV2ItemFieldSingleSelectValue{ name  field { ... on ProjectV2FieldCommon { name }}}
          }}
        }}
      }}
    }"""

    def _load_board(self, board: BoardRef) -> dict:
        return self._graphql(self._PROJECT_QUERY, owner=board.owner, number=board.number)[
            "data"]["user"]["projectV2"]

    @staticmethod
    def _field_index(raw_board: dict) -> dict:
        idx = {}
        for f in raw_board["fields"]["nodes"]:
            if not f:
                continue
            idx[f["name"]] = {"id": f["id"],
                               "options": {o["name"]: o["id"] for o in f.get("options") or []}}
        return idx

    @staticmethod
    def _current_values(item: dict) -> dict:
        out = {}
        for v in item["fieldValues"]["nodes"]:
            name = (v.get("field") or {}).get("name")
            if name:
                out[name] = v.get("text") if "text" in v else v.get("name")
        return out

    def board_fields(self, board: BoardRef) -> dict:
        idx = self._field_index(self._load_board(board))
        return {name: list(info["options"].keys()) for name, info in idx.items()}

    def board_item(self, board: BoardRef, issue_number: int) -> BoardItem | None:
        raw = self._load_board(board)
        for item in raw["items"]["nodes"]:
            content = item.get("content") or {}
            if content.get("number") == issue_number:
                return BoardItem(issue_number=issue_number,
                                  field_values=self._current_values(item))
        return None

    def add_to_board(self, board: BoardRef, issue_number: int) -> None:
        raw = self._load_board(board)
        issue = self.get_issue(issue_number)
        result = self._graphql(
            'mutation($project:ID!, $content:ID!) { addProjectV2ItemById(input:{'
            'projectId:$project contentId:$content }) { item { id } } }',
            project=raw["id"], content=issue.id,
        )
        result["data"]["addProjectV2ItemById"]["item"]["id"]  # raise if the shape is wrong

    def set_board_field(self, board: BoardRef, issue_number: int, field_name: str,
                         value: str) -> None:
        raw = self._load_board(board)
        fields = self._field_index(raw)
        field = fields.get(field_name)
        if field is None:
            raise KeyError(f"field {field_name!r} does not exist on this board")

        item_id = None
        for item in raw["items"]["nodes"]:
            content = item.get("content") or {}
            if content.get("number") == issue_number:
                item_id = item["id"]
                break
        if item_id is None:
            raise KeyError(f"issue #{issue_number} is not on this board")

        if field["options"]:
            option = field["options"].get(value)
            if option is None:
                raise KeyError(f"option {value!r} does not exist on field {field_name!r}")
            payload = f'{{ singleSelectOptionId: "{option}" }}'
        else:
            payload = f'{{ text: "{value}" }}'
        self._graphql(f'''mutation {{ updateProjectV2ItemFieldValue(input:{{
            projectId:"{raw['id']}" itemId:"{item_id}"
            fieldId:"{field['id']}" value:{payload} }}) {{ projectV2Item {{ id }} }} }}''')
