#!/usr/bin/env python3
"""Build the sprint planning ceremony issue — REQ-006, PRD §5.2.

Implements `ceremonies/planning.yaml`. That declaration says the ceremony
should dispatch `role:orchestrator` through `dispatch.yml` — but
`role-packs/orchestrator` is deliberately excluded from `dispatch.yml`'s
role choices (`scripts/test_assign.py`: "the orchestrator is the
dispatcher, not a dispatchee"). Dispatching it as a session would need a
dispatch.yml change that undoes a tested invariant, which is a bigger
change than this ceremony. Instead this script runs the orchestrator's own
logic directly, the same way `orchestrate.yml` runs `scripts/assign.py`
directly rather than dispatching itself — `role: orchestrator` in the
declaration names the pack whose reasoning this implements, not a session
`gh workflow run dispatch.yml` starts.

Capacity is trailing velocity (`dashboards/burndown.py`'s own weekly-bucket
computation, reused rather than reimplemented). Scope is the `status:ready`
queue, oldest first — there is no priority field to sort by yet, so FIFO is
the stated, checkable assumption rather than a silent one. Risk notes are
`status:blocked` / `needs-human` items already open before the sprint
starts.

    scripts/plan.py --repo owner/repo
    scripts/plan.py --repo owner/repo --window-days 28 --dry-run

Creates at most one issue per title (`Sprint Plan: <date>`); reruns on the
same day are idempotent.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CEREMONY_PATH = REPO_ROOT / "ceremonies" / "planning.yaml"
READY = "status:ready"
BLOCKED = "status:blocked"
NEEDS_HUMAN = "needs-human"

# Reuse dashboards/burndown.py's velocity computation instead of
# reimplementing week-bucketing and closed-story counting a second time.
_spec = importlib.util.spec_from_file_location(
    "burndown", REPO_ROOT / "dashboards" / "burndown.py")
BD = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(BD)


def gh(args: list[str]) -> str:
    return subprocess.run(["gh", *args], cwd=REPO_ROOT, check=True,
                          capture_output=True, text=True).stdout


def gh_json(args: list[str], default):
    try:
        out = gh(args)
        return json.loads(out or "null") if out.strip() else default
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"plan: {' '.join(args[:3])} unavailable ({exc.__class__.__name__});"
              f" that section will read as empty", file=sys.stderr)
        return default


def load_ceremony_role(path: Path = CEREMONY_PATH) -> str:
    """The `role:` field, read at run time so the workflow hardcodes
    neither it nor a fallback silently disagreeing with the declaration."""
    if not path.is_file():
        sys.exit(f"plan: missing ceremony declaration {path}")
    try:
        import yaml
        data = yaml.safe_load(path.read_text()) or {}
    except ImportError:
        sys.exit("plan: PyYAML is required to read the ceremony declaration")
    role = data.get("role")
    if not role:
        sys.exit(f"plan: {path} has no 'role' field")
    return role


def collect_ready(repo: str) -> list[dict]:
    issues = gh_json(["issue", "list", "--repo", repo, "--state", "open",
                       "--label", READY, "--limit", "200", "--json",
                       "number,title,url"], [])
    return sorted(issues, key=lambda i: i["number"])


def collect_risk(repo: str) -> list[dict]:
    out = []
    seen = set()
    for label in (BLOCKED, NEEDS_HUMAN):
        for i in gh_json(["issue", "list", "--repo", repo, "--state", "open",
                           "--label", label, "--limit", "200", "--json",
                           "number,title,url,labels"], []):
            if i["number"] in seen:
                continue
            seen.add(i["number"])
            out.append(i)
    return sorted(out, key=lambda i: i["number"])


def existing_titles(repo: str) -> list[str]:
    return [i["title"] for i in gh_json(
        ["issue", "list", "--repo", repo, "--state", "all", "--limit", "500",
         "--json", "title"], [])]


# --------------------------------------------------------------------------
# The computation — pure, so it is testable without a repository
# --------------------------------------------------------------------------

def trailing_capacity(velocity: list[dict], weeks: int = 4) -> tuple[int | None, str]:
    """Average closed-story count over the trailing `weeks` full buckets.

    Returns (capacity, source). `capacity` is None when there is not one
    full window of history yet — the caller states that as an assumption
    rather than fabricating a number (ceremonies/planning.yaml's
    escalates_when)."""
    complete = velocity[-weeks:] if len(velocity) >= weeks else velocity
    if not complete or all(w["closed"] == 0 for w in complete):
        return None, f"no closed stories in the trailing {weeks} week(s) of history"
    total = sum(w["closed"] for w in complete)
    capacity = max(1, round(total / len(complete)))
    return capacity, (f"average of {total} stor(y/ies) closed over "
                      f"{len(complete)} week(s) (dashboards/burndown.py velocity)")


def build_plan(ready: list[dict], risk: list[dict], velocity: list[dict]) -> dict:
    """Pure. Ready queue, risk items and velocity in; the plan out."""
    capacity, capacity_source = trailing_capacity(velocity)
    assumed = capacity is None
    if assumed:
        capacity = 1  # stated assumption, not a fabricated measurement
    scope = ready[:capacity]
    cut_line = ready[capacity:]
    return {
        "capacity": capacity,
        "capacity_assumed": assumed,
        "capacity_source": capacity_source,
        "scope": scope,
        "cut_line": cut_line,
        "risk": risk,
    }


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def render_issue_body(plan: dict, meta: dict) -> str:
    lines = [
        f"Computed from the `{READY}` queue, `{BLOCKED}`/`{NEEDS_HUMAN}` items "
        f"and trailing velocity — implements `ceremonies/planning.yaml` "
        f"(role: `{meta['role']}`, PRD §5.2). No approval label or gate is "
        "wired up yet (ceremonies/planning.yaml's escalates_when names this "
        "as a prerequisite it cannot assume into being); a person reviewing "
        "this issue is today's stand-in for that gate.",
        "",
        "## Capacity",
        "",
    ]
    if plan["capacity_assumed"]:
        lines.append(f"**Assumed** capacity: {plan['capacity']} "
                     f"({plan['capacity_source']}) — not enough trailing "
                     "history to project a burndown, so this is a stated "
                     "assumption, not a measurement.")
    else:
        lines.append(f"Capacity: {plan['capacity']} — {plan['capacity_source']}.")
    lines += ["", "## Scope — this sprint", ""]
    if plan["scope"]:
        for i in plan["scope"]:
            lines.append(f"- [ ] #{i['number']} {i['title']} — {i['url']}")
    else:
        lines.append("_The ready queue is empty — nothing to plan in._")
    lines += ["", "## Cut line — if we're wrong, these drop first", ""]
    if plan["cut_line"]:
        for i in plan["cut_line"]:
            lines.append(f"- #{i['number']} {i['title']} — {i['url']}")
    else:
        lines.append("_Nothing past the cut line — the whole ready queue fits._")
    lines += ["", "## Risk already open before the sprint starts", ""]
    if plan["risk"]:
        for i in plan["risk"]:
            lines.append(f"- #{i['number']} {i['title']} — {i['url']}")
    else:
        lines.append("_No `status:blocked` or `needs-human` item open._")
    lines += ["", f"_Run: {meta.get('run_url', 'n/a')}_"]
    return "\n".join(lines)


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default="Shashank2577/foundry-program")
    ap.add_argument("--window-days", type=int, default=28)
    ap.add_argument("--now", default="", help="ISO timestamp; for reproducible runs")
    ap.add_argument("--dry-run", action="store_true",
                     help="Compute and print the plan; create nothing")
    ap.add_argument("--run-url", default="n/a")
    args = ap.parse_args()

    now = BD.parse_iso(args.now) if args.now else datetime.now(timezone.utc)
    role = load_ceremony_role()
    title = f"Sprint Plan: {now.date()}"

    if title in existing_titles(args.repo):
        print(f"plan: '{title}' already exists — nothing to do")
        return 0

    ready = collect_ready(args.repo)
    risk = collect_risk(args.repo)
    issues = BD.collect_issues()
    report = BD.build_report(issues, now, args.window_days)
    plan = build_plan(ready, risk, report["velocity"])

    print(f"plan: capacity={plan['capacity']}"
          f"{' (assumed)' if plan['capacity_assumed'] else ''}, "
          f"scope={len(plan['scope'])}, cut_line={len(plan['cut_line'])}, "
          f"risk={len(plan['risk'])}")

    meta = {"repo": args.repo, "role": role, "run_url": args.run_url}
    body = render_issue_body(plan, meta)

    if args.dry_run:
        print(f"--- would create issue: {title} ---")
        print(body)
        return 0

    gh(["issue", "create", "--repo", args.repo, "--title", title,
        "--body", body, "--label", "type:task"])
    print(f"plan: created '{title}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
