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

Every tracker operation below goes through `adapters/tracker/base.py`'s
`Tracker` interface (P3-7 / REQ-004) — this file has no `gh` call of its
own. Which implementation backs a run is a single config read,
`make_tracker()`; today that is `TRACKER_IMPL=github` (the default) or
`TRACKER_IMPL=jira`. The Jira path is exercised only against
`adapters/tracker/tests/test_jira.py`'s stubs — there is no live Jira
behind it here (see that package's docstring), so picking it does not
mean Jira integration works, only that the same algorithm runs against it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# `python3 scripts/sync-project.py` puts this file's own directory
# (scripts/) on sys.path, not the repo root — so `adapters` needs help
# to be importable regardless of how this script is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adapters.tracker.base import BoardRef, Issue, Tracker  # noqa: E402
from adapters.tracker.github import GitHubTracker  # noqa: E402

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
    "role:orchestrator": "Orchestrator", "role:product-manager": "PM",
    "role:architect": "Architect", "role:developer": "Developer",
    "role:qa": "QA", "role:devops": "DevOps",
    "role:techwriter": "TechWriter", "role:deliverymanager": "DeliveryManager",
    "role:delivery-lead": "DeliveryManager",
}


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


def _issue_dict(issue: Issue) -> dict:
    """`desired_fields` was written (and is tested) against the dict shape
    `gh issue list --json` returns. Adapt the Tracker's `Issue` to that
    shape rather than changing `desired_fields` — the mapping and its
    tests stay untouched."""
    return {
        "number": issue.number,
        "state": issue.state,
        "body": issue.body,
        "labels": [{"name": name} for name in issue.labels],
    }


# --------------------------------------------------------------------------
# Which tracker backs this run — a config read, not an import choice
# --------------------------------------------------------------------------

def make_tracker() -> Tracker:
    """The one place a run picks its `Tracker` implementation.

    `TRACKER_IMPL=github` (the default) is today's behaviour, unchanged.
    `TRACKER_IMPL=jira` is stub-verified only (see
    `adapters/tracker/jira/client.py`'s docstring and
    `adapters/tracker/tests/test_jira.py`) — there is no live Jira instance
    behind it here, and setting this does not claim there is one.
    """
    impl = os.environ.get("TRACKER_IMPL", "github")
    if impl == "github":
        return GitHubTracker()
    if impl == "jira":
        from adapters.tracker.jira import JiraTracker
        return JiraTracker(
            base_url=os.environ["JIRA_BASE_URL"],
            email=os.environ["JIRA_EMAIL"],
            api_token=os.environ["JIRA_API_TOKEN"],
            project_key=os.environ["JIRA_PROJECT_KEY"],
            field_map=json.loads(os.environ.get("JIRA_FIELD_MAP", "{}")),
            webhook_urls=json.loads(os.environ.get("JIRA_WEBHOOK_URLS", "{}")),
        )
    raise ValueError(f"unknown TRACKER_IMPL: {impl!r} (expected 'github' or 'jira')")


# --------------------------------------------------------------------------
# The world
# --------------------------------------------------------------------------

def apply_fields(tracker: Tracker, board: BoardRef, number: int, board_fields: dict,
                  delta: dict, dry_run: bool) -> int | None:
    """Write every field in `delta`. Returns 1 on failure, None on success."""
    for name, value in delta.items():
        if name not in board_fields:
            print(f"  #{number}: no `{name}` field on this board — skipped")
            continue
        print(f"  #{number}: {name} -> {value}" + ("  (dry run)" if dry_run else ""))
        if dry_run:
            continue
        try:
            tracker.set_board_field(board, number, name, value)
        except (KeyError, subprocess.CalledProcessError) as exc:
            print(f"  #{number}: FAILED to set {name} — {exc}", file=sys.stderr)
            return 1
    return None


def run_sync(tracker: Tracker, board: BoardRef, *, dry_run: bool) -> tuple[int, str]:
    """The whole sync algorithm, independent of argv — so `main()` and tests
    can drive it against any `Tracker`. Returns (exit code, summary line);
    the summary is empty on early failure.

    Only the board-schema read is wrapped against a permission failure —
    that matches the original script, where a `gh` failure anywhere past
    that point was never expected and was left to crash with a traceback
    rather than be mistaken for the same "no `project` scope" cause."""
    try:
        board_fields = tracker.board_fields(board)
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or "").strip().replace("\n", " ")
        print(f"sync-project: cannot read project {board.number} — {err[:300]}",
              file=sys.stderr)
        print("A token with `project` scope is required; GITHUB_TOKEN does not "
              "have it. Set PROJECT_TOKEN.", file=sys.stderr)
        return 2, ""

    issues = {i.number: _issue_dict(i) for i in tracker.list_issues(state="all", limit=200)}

    changes = 0
    unchanged = 0
    on_board = set()
    for number in sorted(issues):
        item = tracker.board_item(board, number)
        if item is None:
            continue
        on_board.add(number)
        delta = diff(item.field_values, desired_fields(issues[number]))
        if not delta:
            unchanged += 1
            continue
        changes += 1
        failed = apply_fields(tracker, board, number, board_fields, delta, dry_run)
        if failed:
            return failed, ""

    added = 0
    for issue_data in plan_additions(issues, on_board):
        number = issue_data["number"]
        added += 1
        changes += 1
        print(f"  #{number}: add to board" + ("  (dry run)" if dry_run else ""))
        if dry_run:
            continue
        try:
            tracker.add_to_board(board, number)
        except KeyError as exc:
            print(f"  #{number}: FAILED to add — {exc}", file=sys.stderr)
            return 1, ""
        failed = apply_fields(tracker, board, number, board_fields,
                               desired_fields(issue_data), dry_run)
        if failed:
            return failed, ""

    verb = "would change" if dry_run else "changed"
    summary = (f"project sync: {verb} {changes} item(s) ({added} added), "
               f"{unchanged} already correct.")
    return 0, summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", type=int, required=True)
    ap.add_argument("--owner", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    tracker = make_tracker()
    board = BoardRef(owner=args.owner, number=args.project)
    code, summary = run_sync(tracker, board, dry_run=args.dry_run)
    if code == 0:
        print(summary)
    return code


if __name__ == "__main__":
    sys.exit(main())
