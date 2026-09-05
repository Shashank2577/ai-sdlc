#!/usr/bin/env python3
"""Build the sprint review ceremony issue — REQ-006, PRD §5.4.

Implements `ceremonies/review.yaml`: one section per story closed in the
window, its acceptance criteria against its QA verdict, plus a summary —
computed from the tracker's own labels and PR links, never a model's
impression of the sprint. `role: techwriter` in the declaration names the
pack that owns and maintains this compiled record (same reading
`ceremonies/standup.yaml` gives `role: devops` for a ceremony that is pure
automation with no agent session, not a session `gh workflow run
dispatch.yml` starts) — techwriter's `write_scope` is `docs/**`, and this
ceremony writes only the tracker.

`qa:approved` / `qa:rejected` reuse `dashboards/qa.py`'s own verdict rule
(rejected outranks approved) so this report and that dashboard can never
disagree. `find_pr_for_issue` reuses `scripts/retro.py`'s branch-name match
rather than reimplementing it.

    scripts/review.py --repo owner/repo
    scripts/review.py --repo owner/repo --window-days 7 --dry-run

Creates one issue per window, titled `Sprint Review: <start> to <end>`,
even when nothing closed — a quiet window is a signal, not a no-op
(ceremonies/review.yaml's escalates_when).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CEREMONY_PATH = REPO_ROOT / "ceremonies" / "review.yaml"

APPROVED, REJECTED, PENDING = "approved", "rejected", "pending"
PR_BRANCH_RE = re.compile(r"^(story|bug)/FDY-(\d+)(-|$)")


def gh(args: list[str]) -> str:
    return subprocess.run(["gh", *args], cwd=REPO_ROOT, check=True,
                          capture_output=True, text=True).stdout


def gh_json(args: list[str], default):
    try:
        out = gh(args)
        return json.loads(out or "null") if out.strip() else default
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"review: {' '.join(args[:3])} unavailable ({exc.__class__.__name__});"
              f" that section will read as empty", file=sys.stderr)
        return default


def load_ceremony_role(path: Path = CEREMONY_PATH) -> str:
    """The `role:` field, read at run time so the workflow hardcodes
    neither it nor a fallback silently disagreeing with the declaration."""
    if not path.is_file():
        sys.exit(f"review: missing ceremony declaration {path}")
    try:
        import yaml
        data = yaml.safe_load(path.read_text()) or {}
    except ImportError:
        sys.exit("review: PyYAML is required to read the ceremony declaration")
    role = data.get("role")
    if not role:
        sys.exit(f"review: {path} has no 'role' field")
    return role


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def window_label(start: datetime, end: datetime) -> str:
    return f"{start.date()} to {end.date()}"


def review_title(start: datetime, end: datetime) -> str:
    return f"Sprint Review: {window_label(start, end)}"


def collect_closed_stories(repo: str) -> list[dict]:
    return gh_json(["issue", "list", "--repo", repo, "--state", "closed",
                     "--label", "type:story", "--limit", "300", "--json",
                     "number,title,url,closedAt,labels,body"], [])


def collect_prs(repo: str) -> list[dict]:
    return gh_json(["pr", "list", "--repo", repo, "--state", "all", "--limit", "300",
                     "--json", "number,url,headRefName,state,mergedAt,closedAt"], [])


def existing_titles(repo: str) -> list[str]:
    return [i["title"] for i in gh_json(
        ["issue", "list", "--repo", repo, "--state", "all", "--limit", "500",
         "--json", "title"], [])]


# --------------------------------------------------------------------------
# The computation — pure, so it is testable without a repository
# --------------------------------------------------------------------------

def verdict(issue: dict) -> str:
    """Rejected outranks approved — dashboards/qa.py's own precedence, so
    this report and that dashboard can never disagree."""
    names = {lbl["name"] for lbl in issue.get("labels", [])}
    if "qa:rejected" in names:
        return REJECTED
    if "qa:approved" in names:
        return APPROVED
    return PENDING


def find_pr_for_issue(prs: list[dict], number: int) -> dict | None:
    matches = [p for p in prs if PR_BRANCH_RE.match(p.get("headRefName") or "")
               and int(PR_BRANCH_RE.match(p["headRefName"]).group(2)) == number]
    if not matches:
        return None
    matches.sort(key=lambda p: (p.get("mergedAt") is None, p.get("state") != "OPEN",
                                p.get("closedAt") or p.get("mergedAt") or ""))
    return matches[0]


def acceptance_criteria(body: str | None) -> list[str]:
    """Gherkin-shaped lines (`Given`/`When`/`Then`/`And`) from the issue
    body — the scenarios written at refinement (PRD §5.1), not the whole
    body verbatim."""
    if not body:
        return []
    return [ln.strip() for ln in body.splitlines()
            if re.match(r"^\s*(Given|When|Then|And)\b", ln.strip())]


def build_review(start: datetime, end: datetime, closed_stories: list[dict],
                 prs: list[dict]) -> dict:
    """Reduce raw event data to the review. No network, no side effects."""
    items = []
    no_verdict = []
    for issue in closed_stories:
        if not (dt := parse_iso(issue.get("closedAt"))) or not (start <= dt <= end):
            continue
        v = verdict(issue)
        pr = find_pr_for_issue(prs, issue["number"])
        entry = {
            "number": issue["number"],
            "title": issue["title"],
            "url": issue["url"],
            "verdict": v,
            "acceptance_criteria": acceptance_criteria(issue.get("body")),
            "pr": {"number": pr["number"], "url": pr["url"]} if pr else None,
        }
        items.append(entry)
        if v == PENDING:
            no_verdict.append(entry)
    items.sort(key=lambda i: i["number"])
    return {
        "window": {"start": start.isoformat(), "end": end.isoformat(),
                   "label": window_label(start, end)},
        "items": items,
        "no_verdict": no_verdict,
        "totals": {
            "shipped": len(items),
            "approved": sum(1 for i in items if i["verdict"] == APPROVED),
            "rejected": sum(1 for i in items if i["verdict"] == REJECTED),
            "pending": len(no_verdict),
        },
    }


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def render_issue_body(review: dict, meta: dict) -> str:
    w, t = review["window"], review["totals"]
    lines = [
        f"Computed from stories closed in **{w['label']}** and their "
        f"`qa:approved`/`qa:rejected` verdicts — implements "
        f"`ceremonies/review.yaml` (role: `{meta['role']}`, PRD §5.4). No "
        "live demo link or client-portal publish: REQ-010 and REQ-008 do "
        "not exist yet, so this ceremony stops at the compiled record, not "
        "silently dropping those steps.",
        "",
        f"{t['shipped']} stor(y/ies) closed · {t['approved']} approved · "
        f"{t['rejected']} rejected · {t['pending']} with no QA verdict.",
        "",
    ]
    if t["pending"]:
        lines += [
            "> **Note:** the item(s) below closed with no `qa:approved` or "
            "`qa:rejected` label at all. REQ-009's veto should make that "
            "impossible — closure without a verdict blocked. Seeing one "
            "here means that veto did not hold; worth a person's "
            "attention independent of this ceremony.",
            "",
        ]
    lines.append("## What shipped")
    lines.append("")
    if not review["items"]:
        lines.append("_Nothing closed in this window — no stories shipped._")
    for i in review["items"]:
        pr_note = f" — {i['pr']['url']}" if i["pr"] else " — no matching PR found"
        lines.append(f"### #{i['number']} {i['title']} ({i['verdict']})")
        lines.append(f"{i['url']}{pr_note}")
        if i["acceptance_criteria"]:
            lines.append("")
            for ac in i["acceptance_criteria"]:
                lines.append(f"- {ac}")
        lines.append("")
    lines += ["## What's next", "",
             "_Carried into the next sprint plan — see the latest "
             "`Sprint Plan:` issue for scope and cut line._"]
    lines += ["", f"_Run: {meta.get('run_url', 'n/a')}_"]
    return "\n".join(lines)


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default="Shashank2577/ai-sdlc")
    ap.add_argument("--window-days", type=int, default=7)
    ap.add_argument("--now", default="", help="ISO timestamp; for reproducible runs")
    ap.add_argument("--dry-run", action="store_true",
                     help="Compute and print the issue; create nothing")
    ap.add_argument("--run-url", default="n/a")
    args = ap.parse_args()

    now = parse_iso(args.now) if args.now else datetime.now(timezone.utc)
    start = now - timedelta(days=args.window_days)
    role = load_ceremony_role()
    title = review_title(start, now)

    if title in existing_titles(args.repo):
        print(f"review: '{title}' already exists — nothing to do")
        return 0

    closed_stories = collect_closed_stories(args.repo)
    prs = collect_prs(args.repo)
    review = build_review(start, now, closed_stories, prs)

    print(f"review: {review['totals']['shipped']} shipped, "
          f"{review['totals']['approved']} approved, "
          f"{review['totals']['rejected']} rejected, "
          f"{review['totals']['pending']} pending")

    meta = {"repo": args.repo, "role": role, "run_url": args.run_url}
    body = render_issue_body(review, meta)

    if args.dry_run:
        print(f"--- would create issue: {title} ---")
        print(body)
        return 0

    gh(["issue", "create", "--repo", args.repo, "--title", title,
        "--body", body, "--label", "type:task"])
    print(f"review: created '{title}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
