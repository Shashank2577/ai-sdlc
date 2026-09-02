#!/usr/bin/env python3
"""The assignment loop: read the board, dispatch what fits under the WIP limit.

Rules live in `role-packs/orchestrator/policy.yaml`, not here. The
selection itself is a pure function of the board, so two runs against the
same board always make the same decisions.

    assign.py --dry-run            # compute and print, dispatch nothing
    assign.py                      # dispatch

Exits 0 with no output on the tracker when nothing is eligible. A loop
that announces "nothing to do" every fifteen minutes gets muted, and then
it is not there when it says something real.
"""

from __future__ import annotations

import argparse
import functools
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = REPO_ROOT / "role-packs" / "orchestrator" / "policy.yaml"

# Used only if the pack is missing entirely. Conservative on purpose: a
# broken policy read must not become an unbounded loop.
FALLBACK_POLICY = {
    "wip": {"limit": 1, "counts": ["status:in-progress"], "per_role": {}},
    "routing": {"prefix": "role:", "supported": ["developer"], "default": None},
    "eligibility": {
        "require_labels": ["status:ready"],
        "exclude_labels": ["needs-human", "status:blocked", "qa:rejected"],
        "require_open": True,
    },
}


def load_policy(path: Path = POLICY_PATH) -> tuple[dict, str]:
    if not path.is_file():
        return FALLBACK_POLICY, f"fallback (no {path.name})"
    try:
        import yaml
        data = yaml.safe_load(path.read_text()) or {}
    except ImportError:
        sys.exit("assign: PyYAML is required to read the orchestrator policy")
    policy = {k: data.get(k, FALLBACK_POLICY[k]) for k in FALLBACK_POLICY}
    if not isinstance(policy["wip"].get("limit"), int) or policy["wip"]["limit"] < 0:
        sys.exit("assign: wip.limit must be a non-negative integer")
    return policy, str(path.relative_to(REPO_ROOT))


# --------------------------------------------------------------------------
# Selection — pure. Board in, plan out.
# --------------------------------------------------------------------------

def labels_of(issue: dict) -> set[str]:
    return {lbl["name"] for lbl in issue.get("labels", [])}


def role_of(issue: dict, routing: dict) -> str | None:
    prefix = routing.get("prefix", "role:")
    found = sorted(n[len(prefix):] for n in labels_of(issue) if n.startswith(prefix))
    if len(found) != 1:
        # Zero is unrefined; two is a contradiction. Neither is a guess we
        # are entitled to make.
        return None
    return found[0] if found[0] in routing.get("supported", []) else None


@functools.lru_cache(maxsize=None)
def dispatchable_from(role: str) -> tuple[str, ...] | None:
    """The states `role-packs/<role>/pack.yaml` declares this role may be
    dispatched from — the same declaration `dispatch.yml`'s guard reads via
    the compiler (#67). None means the pack declares nothing (or cannot be
    read), and the caller falls back to `eligibility.require_labels`: that
    fallback is for a silent pack, not the rule for every role.
    """
    path = REPO_ROOT / "role-packs" / role / "pack.yaml"
    if not path.is_file():
        return None
    try:
        import yaml
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:
        return None
    states = data.get("dispatchable_from")
    if not isinstance(states, list) or not states or not all(isinstance(s, str) for s in states):
        return None
    return tuple(states)


def ineligible_reason(issue: dict, policy: dict) -> str | None:
    """None means eligible. Otherwise a sentence a human can act on."""
    elig, routing = policy["eligibility"], policy["routing"]
    names = labels_of(issue)

    if elig.get("require_open", True) and issue.get("state") != "OPEN":
        return "not open"
    blocking = [l for l in elig.get("exclude_labels", []) if l in names]
    if blocking:
        return f"carries {', '.join(blocking)}"

    prefix = routing.get("prefix", "role:")
    role_labels = [n for n in names if n.startswith(prefix)]
    if not role_labels:
        return f"no `{prefix}*` label — refinement is not finished"
    if len(role_labels) > 1:
        return f"several role labels ({', '.join(sorted(role_labels))})"
    role = role_of(issue, routing)
    if role is None:
        return (f"role `{role_labels[0][len(prefix):]}` is not dispatchable "
                f"(supported: {', '.join(routing.get('supported', []))})")

    entry_states = dispatchable_from(role) or tuple(elig.get("require_labels", []))
    if entry_states and not (set(entry_states) & names):
        if len(entry_states) == 1:
            return f"missing {entry_states[0]}"
        return f"missing one of {', '.join(entry_states)}"
    return None


def sort_key(issue: dict, with_open_pr: set[int]) -> tuple:
    # Finishing beats starting; then lowest number. Deterministic on purpose
    # — a clever order nobody can predict is worse than a dull one.
    return (0 if issue["number"] in with_open_pr else 1, issue["number"])


def plan(issues: list[dict], policy: dict, with_open_pr: set[int] | None = None) -> dict:
    with_open_pr = with_open_pr or set()
    wip, routing = policy["wip"], policy["routing"]
    counts = set(wip.get("counts", ["status:in-progress"]))

    in_flight = [i for i in issues
                 if i.get("state") == "OPEN" and labels_of(i) & counts]
    in_flight_by_role = {}
    for issue in in_flight:
        role = role_of(issue, routing)
        if role:
            in_flight_by_role[role] = in_flight_by_role.get(role, 0) + 1

    eligible, skipped = [], []
    for issue in issues:
        reason = ineligible_reason(issue, policy)
        if reason is None:
            eligible.append(issue)
        elif issue.get("state") == "OPEN":
            skipped.append({"number": issue["number"], "title": issue.get("title", ""),
                            "reason": reason})

    slots = max(wip["limit"] - len(in_flight), 0)
    per_role = wip.get("per_role") or {}
    dispatch, deferred = [], []

    for issue in sorted(eligible, key=lambda i: sort_key(i, with_open_pr)):
        role = role_of(issue, routing)
        entry = {"number": issue["number"], "title": issue.get("title", ""),
                 "role": role, "url": issue.get("url", "")}
        if len(dispatch) >= slots:
            entry["reason"] = f"WIP limit {wip['limit']} reached"
            deferred.append(entry)
            continue
        cap = per_role.get(role)
        used = in_flight_by_role.get(role, 0) + sum(1 for d in dispatch if d["role"] == role)
        if cap is not None and used >= cap:
            entry["reason"] = f"per-role cap for `{role}` is {cap}"
            deferred.append(entry)
            continue
        dispatch.append(entry)

    return {
        "limit": wip["limit"],
        "in_flight": len(in_flight),
        "in_flight_numbers": sorted(i["number"] for i in in_flight),
        "slots": slots,
        "dispatch": dispatch,
        "deferred": deferred,
        "skipped": sorted(skipped, key=lambda s: s["number"]),
        "eligible_total": len(eligible),
    }


# --------------------------------------------------------------------------
# The world
# --------------------------------------------------------------------------

def gh(args: list[str]) -> str:
    return subprocess.run(["gh", *args], cwd=REPO_ROOT, check=True,
                          capture_output=True, text=True).stdout


def collect_issues() -> list[dict]:
    return json.loads(gh(["issue", "list", "--state", "open", "--limit", "200",
                          "--json", "number,title,state,labels,url"]) or "[]")


def collect_issues_with_open_prs() -> set[int]:
    """Issue numbers that already have a branch and PR in flight."""
    pulls = json.loads(gh(["pr", "list", "--state", "open", "--limit", "100",
                           "--json", "headRefName"]) or "[]")
    out = set()
    for pr in pulls:
        m = re.match(r"^(?:story|bug)/FDY-(\d+)-", pr.get("headRefName", ""))
        if m:
            out.add(int(m.group(1)))
    return out


def dispatch_one(entry: dict) -> tuple[bool, str]:
    try:
        gh(["workflow", "run", "dispatch.yml",
            "-f", f"issue={entry['number']}", "-f", f"role={entry['role']}"])
        return True, ""
    except subprocess.CalledProcessError as exc:
        return False, (exc.stderr or exc.stdout or "").strip().replace("\n", " ")[:300]


def render_plan(p: dict, source: str) -> str:
    lines = [
        f"Board: {p['in_flight']}/{p['limit']} in flight"
        + (f" {p['in_flight_numbers']}" if p["in_flight_numbers"] else "")
        + f", {p['slots']} slot(s) free, "
        f"{p['eligible_total']} eligible. Policy: {source}",
    ]
    for d in p["dispatch"]:
        lines.append(f"  dispatch #{d['number']} as {d['role']} — {d['title'][:60]}")
    for d in p["deferred"]:
        lines.append(f"  defer    #{d['number']} — {d['reason']}")
    for s in p["skipped"]:
        lines.append(f"  skip     #{s['number']} — {s['reason']}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true", help="print the plan as JSON")
    args = ap.parse_args()

    policy, source = load_policy()
    issues = collect_issues()
    p = plan(issues, policy, collect_issues_with_open_prs())

    if args.json:
        print(json.dumps({**p, "policy_source": source}, indent=2))
        return 0

    report = render_plan(p, source)
    print(report)

    summary = []
    if not p["dispatch"]:
        # The quiet exit. The run log says what was considered; the tracker
        # hears nothing, because there is nothing worth a notification.
        summary = ["## Assignment loop — nothing dispatched", "", "```", report, "```"]
    else:
        summary = ["## Assignment loop", "", "```", report, "```"]

    failures = 0
    if not args.dry_run:
        for entry in p["dispatch"]:
            ok, err = dispatch_one(entry)
            if ok:
                print(f"dispatched #{entry['number']} as {entry['role']}")
                summary.append(f"- dispatched #{entry['number']} as `{entry['role']}`")
            else:
                failures += 1
                print(f"FAILED to dispatch #{entry['number']}: {err}", file=sys.stderr)
                summary.append(f"- **failed** to dispatch #{entry['number']}: `{err}`")
    elif p["dispatch"]:
        summary.append("")
        summary.append("_Dry run — nothing was dispatched._")

    import os
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a") as fh:
            fh.write("\n".join(summary) + "\n")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
