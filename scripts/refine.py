#!/usr/bin/env python3
"""The refinement trigger: dispatch the PM when the ready queue empties.

Rules live in `role-packs/orchestrator/policy.yaml:refill`, not here — a
floor, not a calendar, so refinement fires on an emptying board rather
than on a schedule that writes stories nobody asked for.

    refine.py --dry-run            # compute and print, dispatch nothing
    refine.py                      # dispatch if the floor is at or under

Exits 0 with no tracker comment when the board is not at the floor. A
loop that announces "nothing to do" every hour gets muted, and then it
is not there when it says something real — same reasoning as
`scripts/assign.py`.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = REPO_ROOT / "role-packs" / "orchestrator" / "policy.yaml"
READY = "status:ready"

# Used only if the pack is missing entirely. Conservative on purpose: a
# broken policy read must not become a silent no-op nor an unbounded loop.
FALLBACK_REFILL = {
    "ready_floor": 1,
    "scope_source": "requirements/coverage.yaml",
    "role": "product-manager",
}


def load_refill_policy(path: Path = POLICY_PATH) -> tuple[dict, str]:
    if not path.is_file():
        return FALLBACK_REFILL, f"fallback (no {path.name})"
    try:
        import yaml
        data = yaml.safe_load(path.read_text()) or {}
    except ImportError:
        sys.exit("refine: PyYAML is required to read the orchestrator policy")
    refill = data.get("refill") or {}
    policy = {k: refill.get(k, FALLBACK_REFILL[k]) for k in FALLBACK_REFILL}
    if not isinstance(policy["ready_floor"], int) or policy["ready_floor"] < 0:
        sys.exit("refine: refill.ready_floor must be a non-negative integer")
    if not policy.get("role"):
        sys.exit("refine: refill.role must be set")
    return policy, str(path.relative_to(REPO_ROOT))


# --------------------------------------------------------------------------
# Decision — pure. Board in, plan out.
# --------------------------------------------------------------------------

def should_refine(ready_count: int, floor: int) -> bool:
    """A floor, not a schedule: fire only once the queue is at or below it."""
    return ready_count <= floor


def plan_refill(ready_count: int, floor: int, pm_issues: list[dict]) -> dict:
    """Pure. The ready count and the board's existing PM work in, one of
    four actions out:

    - quiet   — above the floor, nothing to do.
    - dispatch — an open, already-`status:ready` PM item exists; run it.
    - wait    — a PM item exists but nobody has approved it yet (or it is
                already in flight); do not create a second one, and do not
                dispatch what a person has not cleared.
    - create  — the floor is hit and no PM item exists at all; this is the
                board-ran-dry case the story exists for.
    """
    base = {"ready_count": ready_count, "floor": floor}
    if not should_refine(ready_count, floor):
        return {**base, "action": "quiet"}

    candidates = sorted(pm_issues, key=lambda i: i["number"])
    for issue in candidates:
        if READY in issue.get("labels", []):
            return {**base, "action": "dispatch", "number": issue["number"]}
    if candidates:
        return {**base, "action": "wait", "number": candidates[0]["number"]}
    return {**base, "action": "create"}


def render_plan(p: dict, source: str) -> str:
    header = (f"Ready queue: {p['ready_count']} (floor {p['floor']}). "
              f"Policy: {source}")
    body = {
        "quiet": "above the floor — nothing to do.",
        "dispatch": f"at/below the floor — dispatching existing #{p.get('number')}.",
        "wait": (f"at/below the floor, but #{p.get('number')} is already open "
                f"and not yet `{READY}` — waiting on a person, not creating "
                "a duplicate."),
        "create": "at/below the floor and no PM work item exists — opening one.",
    }[p["action"]]
    return f"{header}\n  {p['action']}: {body}"


# --------------------------------------------------------------------------
# The world
# --------------------------------------------------------------------------

def gh(args: list[str]) -> str:
    return subprocess.run(["gh", *args], cwd=REPO_ROOT, check=True,
                          capture_output=True, text=True).stdout


def count_ready() -> int:
    out = gh(["issue", "list", "--state", "open", "--label", READY,
              "--limit", "200", "--json", "number"])
    return len(json.loads(out or "[]"))


def list_role_issues(role: str) -> list[dict]:
    out = gh(["issue", "list", "--state", "open", "--label", f"role:{role}",
              "--limit", "50", "--json", "number,labels"])
    issues = json.loads(out or "[]")
    return [{"number": i["number"], "labels": [l["name"] for l in i["labels"]]}
            for i in issues]


def create_refill_issue(role: str, scope_source: str) -> int:
    """Open the one work item this cycle needs: a PM ask fenced to
    unsatisfied criteria, non-critical per `policies/gates.yaml`
    (role:product-manager is not in `critical_when`), so an agent applying
    `status:ready` to its own routine ask is the documented default —
    "Routine work is dispatched on an agent's own say-so" — not a gate this
    workflow is inventing.
    """
    title = "Backlog refill — refine toward unsatisfied requirements"
    body = (
        "Opened automatically: the ready queue emptied "
        "(`role-packs/orchestrator/policy.yaml:refill`).\n\n"
        f"**As the** delivery org **I want** the backlog refilled **so "
        "that** developer sessions do not stall waiting on a person to "
        "write the next story.\n\n"
        f"Scope is fenced by `{scope_source}`'s unsatisfied criteria — "
        "refine toward those, not toward whatever seems interesting. "
        "Propose stories only; this item does not authorize you to "
        "self-approve them.\n"
    )
    out = gh(["issue", "create", "--title", title, "--body", body,
              "--label", "type:task", "--label", f"role:{role}",
              "--label", READY])
    # `gh issue create` prints the issue URL; the number is its last segment.
    return int(out.strip().rstrip("/").rsplit("/", 1)[-1])


def dispatch(number: int, role: str) -> tuple[bool, str]:
    try:
        gh(["workflow", "run", "dispatch.yml",
            "-f", f"issue={number}", "-f", f"role={role}"])
        return True, ""
    except subprocess.CalledProcessError as exc:
        return False, (exc.stderr or exc.stdout or "").strip().replace("\n", " ")[:300]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    policy, source = load_refill_policy()
    role = policy["role"]

    ready_count = count_ready()
    pm_issues = list_role_issues(role) if should_refine(ready_count, policy["ready_floor"]) else []
    p = plan_refill(ready_count, policy["ready_floor"], pm_issues)

    report = render_plan(p, source)
    print(report)

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    summary_lines = None  # only written for a non-quiet decision

    if p["action"] == "quiet":
        return 0

    if args.dry_run:
        print("Dry run — nothing was dispatched or created.")
        summary_lines = ["## Refinement trigger — dry run", "", "```", report, "```"]
    elif p["action"] == "wait":
        summary_lines = ["## Refinement trigger — waiting on a person", "", "```", report, "```"]
    else:
        number = p.get("number")
        if p["action"] == "create":
            number = create_refill_issue(role, policy["scope_source"])
            print(f"created #{number} as {role}, labelled {READY}")
        ok, err = dispatch(number, role)
        if ok:
            print(f"dispatched #{number} as {role}")
            summary_lines = ["## Refinement trigger", "", "```", report, "```",
                             f"- dispatched #{number} as `{role}`"]
        else:
            print(f"FAILED to dispatch #{number}: {err}", file=sys.stderr)
            summary_lines = ["## Refinement trigger — dispatch failed", "", "```", report, "```",
                             f"- **failed** to dispatch #{number}: `{err}`"]
            if step_summary:
                with open(step_summary, "a") as fh:
                    fh.write("\n".join(summary_lines) + "\n")
            return 1

    if step_summary and summary_lines:
        with open(step_summary, "a") as fh:
            fh.write("\n".join(summary_lines) + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
