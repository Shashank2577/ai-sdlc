#!/usr/bin/env python3
"""Build the retro ceremony issue — event-derived, one issue per window.

Nobody is asked what went well or what to change. The retro is computed
from closed work items, the dispatcher's own session-end comments
(`foundry:dispatch result=`), escalation comments, and check-run failures
in the window (REQ-006, REQ-013) — the same "events, not self-reports"
rule `dashboards/standup.py` follows, including its fixed-`now` testing
approach, because every interesting case here is a window boundary too.

    scripts/retro.py --repo owner/repo
    scripts/retro.py --repo owner/repo --window-days 7 \\
        --now 2026-09-02T00:00:00Z --dry-run

Creates at most one issue per window, titled `Retro: <start> to <end>`.
PRD §12 routes retro-accepted learnings into role-pack skills through a
reviewed pull request, decided by a person — this script only observes.
It proposes no skill edit and opens no pull request.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DISPATCH_RE = re.compile(
    r"<!--\s*foundry:dispatch\s+result=(?P<result>\S+)\s+outcome=(?P<outcome>\S+)"
    r"\s+breach=(?P<breach>\S+)\s*-->")
ROLE_RE = re.compile(r"[Tt]he `([\w.-]+)` session")
RUN_ROW_RE = re.compile(r"\|\s*Run\s*\|\s*(\S+)\s*\|")
COST_ROW_RE = re.compile(r"\|\s*cost \(USD\)\s*\|\s*([\d.]+|unknown)\s*\|")
ESCALATION_MARK = "### Escalation"
RETRO_LABEL = "process"  # `policy` labelling calls for `type:process`; the
                          # repo's actual label (gh label list) is `process`
                          # — described as "Retro-driven process
                          # improvement", which is this label.


def gh(args: list[str]) -> str:
    return subprocess.run(["gh", *args], cwd=REPO_ROOT, check=True,
                           capture_output=True, text=True).stdout


def gh_json(args: list[str], default):
    try:
        out = gh(args)
        return json.loads(out or "null") if out.strip() else default
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"retro: {' '.join(args[:3])} unavailable ({exc.__class__.__name__});"
              f" that section will read as empty", file=sys.stderr)
        return default


def gh_jsonl(args: list[str], default):
    try:
        out = gh(args)
    except subprocess.CalledProcessError as exc:
        print(f"retro: {' '.join(args[:3])} unavailable ({exc.__class__.__name__});"
              f" that section will read as empty", file=sys.stderr)
        return default
    rows = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows or default


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def window_label(start: datetime, end: datetime) -> str:
    return f"{start.date()} to {end.date()}"


def retro_title(start: datetime, end: datetime) -> str:
    return f"Retro: {window_label(start, end)}"


# --------------------------------------------------------------------------
# Collection
# --------------------------------------------------------------------------

def collect_closed_issues(repo: str) -> list[dict]:
    return gh_json(["issue", "list", "--repo", repo, "--state", "closed",
                     "--limit", "300", "--json",
                     "number,title,url,closedAt,labels"], [])


def collect_comments(repo: str, issue_number: int) -> list[dict]:
    return gh_jsonl(["api", "--paginate",
                      f"repos/{repo}/issues/{issue_number}/comments",
                      "--jq", ".[] | {body: .body, url: .html_url, created_at: .created_at}"],
                     [])


def collect_prs(repo: str) -> list[dict]:
    return gh_json(["pr", "list", "--repo", repo, "--state", "all", "--limit", "300",
                     "--json", "number,url,headRefName,state,mergedAt,closedAt"], [])


def collect_runs(repo: str) -> list[dict]:
    return gh_json(["run", "list", "--repo", repo, "--limit", "200", "--json",
                     "databaseId,name,conclusion,createdAt,headBranch,url,event"], [])


def existing_titles(repo: str) -> list[str]:
    return [i["title"] for i in gh_json(
        ["issue", "list", "--repo", repo, "--state", "all", "--limit", "500",
         "--json", "title"], [])]


# --------------------------------------------------------------------------
# The computation — pure, so it is testable without a repository
# --------------------------------------------------------------------------

def find_pr_for_issue(prs: list[dict], number: int) -> dict | None:
    pattern = re.compile(rf"^(story|bug)/FDY-{number}(-|$)")
    matches = [p for p in prs if pattern.match(p.get("headRefName") or "")]
    if not matches:
        return None
    matches.sort(key=lambda p: (
        p.get("mergedAt") is None,           # merged first
        p.get("state") != "OPEN",            # then open
        p.get("closedAt") or p.get("mergedAt") or "",
    ))
    return matches[0]


def extract_sessions(comments: list[dict]) -> list[dict]:
    sessions = []
    for c in comments:
        body = c.get("body") or ""
        m = DISPATCH_RE.search(body)
        if not m:
            continue
        role_m = ROLE_RE.search(body)
        cost_m = COST_ROW_RE.search(body)
        run_m = RUN_ROW_RE.search(body)
        cost = None
        if cost_m and cost_m.group(1) != "unknown":
            cost = float(cost_m.group(1))
        sessions.append({
            "result": m.group("result"),
            "outcome": m.group("outcome"),
            "breach": m.group("breach"),
            "role": role_m.group(1) if role_m else "unknown",
            "cost_usd": cost,
            "run_url": run_m.group(1) if run_m else None,
            "comment_url": c.get("url", ""),
        })
    return sessions


def extract_escalations(comments: list[dict]) -> list[dict]:
    out = []
    for c in comments:
        body = c.get("body") or ""
        if ESCALATION_MARK not in body:
            continue
        heading = next((ln for ln in body.splitlines() if ln.strip()), "").strip("# ").strip()
        out.append({"comment_url": c.get("url", ""), "heading": heading or "Escalation"})
    return out


def build_retro(now: datetime, window_days: int, closed_issues: list[dict],
                 comments_by_issue: dict[int, list[dict]], prs: list[dict],
                 runs: list[dict]) -> dict:
    """Reduce raw event data to the retro. No network, no side effects."""
    start = now - timedelta(days=window_days)

    def in_window(value: str | None) -> bool:
        dt = parse_iso(value)
        return dt is not None and start <= dt <= now

    items = []
    for issue in closed_issues:
        if not in_window(issue.get("closedAt")):
            continue
        if any(lbl.get("name") == RETRO_LABEL for lbl in issue.get("labels", [])):
            continue  # a prior retro issue is process output, not a work item
        comments = comments_by_issue.get(issue["number"], [])
        sessions = extract_sessions(comments)
        escalations = extract_escalations(comments)
        pr = find_pr_for_issue(prs, issue["number"])
        costs = [s["cost_usd"] for s in sessions if s["cost_usd"] is not None]
        items.append({
            "number": issue["number"],
            "title": issue["title"],
            "url": issue["url"],
            "closed_at": issue["closedAt"],
            "pr": {"number": pr["number"], "url": pr["url"]} if pr else None,
            "sessions": sessions,
            "failed_sessions": [s for s in sessions if s["result"] == "failure"],
            "escalations": escalations,
            "cost_total": round(sum(costs), 4) if costs else None,
        })
    items.sort(key=lambda i: i["closed_at"] or "")

    failures = [r for r in runs
                if r.get("conclusion") == "failure" and in_window(r.get("createdAt"))]

    totals = {
        "items": len(items),
        "sessions": sum(len(i["sessions"]) for i in items),
        "failed_sessions": sum(len(i["failed_sessions"]) for i in items),
        "escalations": sum(len(i["escalations"]) for i in items),
        "cost_usd": round(sum(i["cost_total"] or 0 for i in items), 4),
        "check_failures": len(failures),
    }

    return {
        "window": {"start": start.isoformat(), "end": now.isoformat(),
                   "label": window_label(start, now)},
        "items": items,
        "check_failures": [{"name": r.get("name"), "branch": r.get("headBranch"),
                            "url": r.get("url"), "at": r.get("createdAt")}
                           for r in failures],
        "totals": totals,
    }


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def render_issue_body(retro: dict, meta: dict) -> str:
    w = retro["window"]
    t = retro["totals"]
    lines = [
        f"Computed from events in **{w['label']}** "
        f"({w['start']} to {w['end']}), for {meta.get('repo', '')}. "
        "Nobody was asked what went well or what to change; every line "
        "below cites the run, comment or pull request it came from "
        "(REQ-006).",
        "",
        f"{t['items']} work item(s) closed · {t['sessions']} dispatch "
        f"session(s) ({t['failed_sessions']} failed) · "
        f"{t['escalations']} escalation(s) · ${t['cost_usd']:.2f} spent · "
        f"{t['check_failures']} check failure(s) in the window.",
        "",
        "## What the events show",
        "",
    ]

    for item in retro["items"]:
        lines.append(f"### #{item['number']} — {item['title']}")
        lines.append(f"[{item['url']}]({item['url']}), closed {item['closed_at']}")
        if item["pr"]:
            lines.append(f"PR: [#{item['pr']['number']}]({item['pr']['url']})")
        if not item["sessions"]:
            lines.append("- No dispatcher session-end comment found on this item.")
        for s in item["sessions"]:
            cost = f"${s['cost_usd']:.2f}" if s["cost_usd"] is not None else "cost unknown"
            cite = f"[run]({s['run_url']})" if s["run_url"] else f"[comment]({s['comment_url']})"
            lines.append(
                f"- `{s['role']}` session — result `{s['result']}`, "
                f"outcome `{s['outcome']}`, breach `{s['breach']}`, {cost} — {cite}")
        for e in item["escalations"]:
            lines.append(f"- Escalation: {e['heading']} — [comment]({e['comment_url']})")
        lines.append("")

    if not retro["items"]:
        lines.append("_No closed work items cited any dispatch session in this window._")
        lines.append("")

    lines.append("## Check failures in the window")
    lines.append("")
    if retro["check_failures"]:
        for f in retro["check_failures"]:
            lines.append(f"- [{f['name']}]({f['url']}) on `{f['branch']}` at {f['at']}")
    else:
        lines.append("_None._")
    lines.append("")

    lines.append("## What this issue is not")
    lines.append("")
    lines.append(
        "This observes; it does not propose a skill edit. Promoting anything "
        "above into a role-pack skill needs its own reviewed pull request, "
        "decided by a person (PRD §12, `policies/gates.yaml`).")
    lines.append("")
    lines.append(f"_Generated by `scripts/retro.py`, run {meta.get('run_url', 'n/a')}._")
    return "\n".join(lines) + "\n"


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
    title = retro_title(start, now)

    if title in existing_titles(args.repo):
        print(f"retro: '{title}' already exists — nothing to do")
        return 0

    closed_issues = collect_closed_issues(args.repo)
    in_scope = [i for i in closed_issues
                if (dt := parse_iso(i.get("closedAt"))) and start <= dt <= now]
    comments_by_issue = {i["number"]: collect_comments(args.repo, i["number"])
                         for i in in_scope}
    prs = collect_prs(args.repo)
    runs = collect_runs(args.repo)

    retro = build_retro(now, args.window_days, closed_issues, comments_by_issue, prs, runs)

    if not retro["items"]:
        print(f"retro: no closed work items in {retro['window']['label']} — "
              f"no issue created")
        return 0

    meta = {"repo": args.repo, "run_url": args.run_url}
    body = render_issue_body(retro, meta)

    print(f"retro: {retro['totals']['items']} item(s), "
          f"{retro['totals']['sessions']} session(s), "
          f"{retro['totals']['escalations']} escalation(s), "
          f"${retro['totals']['cost_usd']:.2f} spent, "
          f"{retro['totals']['check_failures']} check failure(s)")

    if args.dry_run:
        print(f"--- would create issue: {title} ---")
        print(body)
        return 0

    gh(["issue", "create", "--repo", args.repo, "--title", title,
        "--body", body, "--label", RETRO_LABEL])
    print(f"retro: created '{title}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
