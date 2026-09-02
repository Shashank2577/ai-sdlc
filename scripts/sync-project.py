#!/usr/bin/env python3
"""Make the project board reflect the repository, not somebody's memory.

Labels are the state machine (CONVENTIONS.md). The board is a view of
them. This computes every board field from issue state and writes back
only what differs — so the board can be trusted without being tended.

    sync-project.py --project 2 --owner Shashank2577 --dry-run
    sync-project.py --project 2 --owner Shashank2577

Writing to a user-level Project v2 needs a token with `project` scope;
GITHUB_TOKEN does not have it. Without one this reports the plan and
changes nothing, which is the honest failure for a scheduled job.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

REQ = re.compile(r"REQ-\d{3}")
# Stories end their user-story line with `→ **REQ-002, REQ-003**`. When that
# marker is present it is authoritative; scraping the whole body would pick
# up any REQ mentioned in passing in the acceptance criteria and invent a
# link nobody asserted.
REQ_MARKER = re.compile(r"→\s*\*\*((?:REQ-\d{3}[,\s]*)+)\*\*")

# label -> board Status. Order matters: the first match wins, so a story
# that somehow carries two status labels resolves the same way every run.
STATUS_BY_LABEL = [
    ("status:blocked", "Blocked"),
    ("status:in-review", "In Review"),
    ("status:in-progress", "In Progress"),
    ("status:ready", "Ready"),
    ("status:needs-refinement", "Needs Refinement"),
]
QA_BY_LABEL = [("qa:rejected", "Rejected"), ("qa:approved", "Approved")]

ROLE_BY_LABEL = {
    "role:orchestrator": "Orchestrator", "role:pm": "PM",
    "role:architect": "Architect", "role:developer": "Developer",
    "role:qa": "QA", "role:devops": "DevOps",
    "role:techwriter": "TechWriter", "role:deliverymanager": "DeliveryManager",
}


def gh_json(args: list[str]):
    out = subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout
    return json.loads(out or "null")


def graphql(query: str, **variables):
    args = ["api", "graphql", "-f", f"query={query}"]
    for k, v in variables.items():
        args += ["-f", f"{k}={v}"]
    return gh_json(args)


# --------------------------------------------------------------------------
# The computation — pure, so the mapping is testable without a project
# --------------------------------------------------------------------------

def desired_fields(issue: dict) -> dict:
    """What the board should say about this issue, from the issue alone."""
    labels = {l["name"] for l in issue.get("labels", [])}
    closed = issue.get("state", "").upper() == "CLOSED"

    # Closed outranks every label. An item can carry a stale status label —
    # closed is a fact, so it wins.
    status = "Done" if closed else None
    if status is None:
        for label, value in STATUS_BY_LABEL:
            if label in labels:
                status = value
                break
        else:
            status = "Todo"

    role = None
    for label, value in ROLE_BY_LABEL.items():
        if label in labels:
            role = value
            break

    qa = "Pending"
    for label, value in QA_BY_LABEL:
        if label in labels:
            qa = value
            break

    body = issue.get("body") or ""
    marker = REQ_MARKER.search(body)
    reqs = sorted(set(REQ.findall(marker.group(1) if marker else body)))
    out = {"Status": status, "QA-Verdict": qa}
    if role:
        out["Role"] = role
    if reqs:
        out["Requirement-ID"] = ", ".join(reqs)
    return out


def diff(current: dict, desired: dict) -> dict:
    """Only what actually differs. A no-op run must write nothing."""
    return {k: v for k, v in desired.items() if current.get(k) != v}


def plan_additions(issues: dict, on_board: set) -> list:
    """Open issues missing from the board — sorted so a run is deterministic.

    Closed issues that were never added are somebody else's call, not this
    job's: backfilling history is different from keeping the board current.
    """
    return sorted(
        (issue for number, issue in issues.items()
         if number not in on_board and issue.get("state", "").upper() == "OPEN"),
        key=lambda issue: issue["number"])


# --------------------------------------------------------------------------
# The world
# --------------------------------------------------------------------------

PROJECT_QUERY = """
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


def load_board(owner: str, number: int) -> dict:
    # -F rather than -f: the query needs a real Int, and gh sends -f as a string.
    out = subprocess.run(
        ["gh", "api", "graphql", "-f", f"query={PROJECT_QUERY}",
         "-f", f"owner={owner}", "-F", f"number={number}"],
        check=True, capture_output=True, text=True).stdout
    return json.loads(out)["data"]["user"]["projectV2"]


def field_index(board: dict) -> dict:
    idx = {}
    for f in board["fields"]["nodes"]:
        if not f:
            continue
        idx[f["name"]] = {"id": f["id"],
                          "options": {o["name"]: o["id"] for o in f.get("options") or []}}
    return idx


def current_values(item: dict) -> dict:
    out = {}
    for v in item["fieldValues"]["nodes"]:
        name = (v.get("field") or {}).get("name")
        if name:
            out[name] = v.get("text") if "text" in v else v.get("name")
    return out


def write_field(project_id: str, item_id: str, field: dict, value: str) -> None:
    if field["options"]:
        option = field["options"].get(value)
        if option is None:
            raise KeyError(f"option {value!r} does not exist on this field")
        payload = f'{{ singleSelectOptionId: "{option}" }}'
    else:
        payload = f'{{ text: "{value}" }}'
    graphql(f'''mutation {{ updateProjectV2ItemFieldValue(input:{{
        projectId:"{project_id}" itemId:"{item_id}"
        fieldId:"{field['id']}" value:{payload} }}) {{ projectV2Item {{ id }} }} }}''')


def add_item(project_id: str, content_id: str) -> str:
    """Add an issue to the board and return the new item's id."""
    result = graphql(f'''mutation {{ addProjectV2ItemById(input:{{
        projectId:"{project_id}" contentId:"{content_id}" }}) {{ item {{ id }} }} }}''')
    return result["data"]["addProjectV2ItemById"]["item"]["id"]


def apply_fields(project_id: str, item_id: str, number: int, fields: dict,
                  delta: dict, dry_run: bool) -> int | None:
    """Write every field in `delta`. Returns 1 on failure, None on success."""
    for name, value in delta.items():
        field = fields.get(name)
        if not field:
            print(f"  #{number}: no `{name}` field on this board — skipped")
            continue
        print(f"  #{number}: {name} -> {value}" + ("  (dry run)" if dry_run else ""))
        if dry_run:
            continue
        try:
            write_field(project_id, item_id, field, value)
        except (KeyError, subprocess.CalledProcessError) as exc:
            print(f"  #{number}: FAILED to set {name} — {exc}", file=sys.stderr)
            return 1
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", type=int, required=True)
    ap.add_argument("--owner", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        board = load_board(args.owner, args.project)
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or "").strip().replace("\n", " ")
        print(f"sync-project: cannot read project {args.project} — {err[:300]}",
              file=sys.stderr)
        print("A token with `project` scope is required; GITHUB_TOKEN does not "
              "have it. Set PROJECT_TOKEN.", file=sys.stderr)
        return 2

    fields = field_index(board)
    issues = {i["number"]: i for i in gh_json(
        ["issue", "list", "--state", "all", "--limit", "200",
         "--json", "number,title,state,labels,body,id"])}

    changes = 0
    unchanged = 0
    on_board = set()
    for item in board["items"]["nodes"]:
        content = item.get("content") or {}
        number = content.get("number")
        if number is None or number not in issues:
            continue
        on_board.add(number)
        delta = diff(current_values(item), desired_fields(issues[number]))
        if not delta:
            unchanged += 1
            continue
        changes += 1
        failed = apply_fields(board["id"], item["id"], number, fields, delta, args.dry_run)
        if failed:
            return failed

    added = 0
    for issue_data in plan_additions(issues, on_board):
        number = issue_data["number"]
        added += 1
        changes += 1
        print(f"  #{number}: add to board" + ("  (dry run)" if args.dry_run else ""))
        if args.dry_run:
            continue
        try:
            item_id = add_item(board["id"], issue_data["id"])
        except subprocess.CalledProcessError as exc:
            print(f"  #{number}: FAILED to add — {exc}", file=sys.stderr)
            return 1
        failed = apply_fields(board["id"], item_id, number, fields,
                               desired_fields(issue_data), args.dry_run)
        if failed:
            return failed

    verb = "would change" if args.dry_run else "changed"
    print(f"project sync: {verb} {changes} item(s) ({added} added), "
          f"{unchanged} already correct.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
