#!/usr/bin/env python3
"""Build the daily standup digest — from events, never from self-reports.

Nobody is asked what they did. The digest is computed from commits and
their trailers, pull request state transitions, workflow run conclusions,
and label history. An agent that claims progress it did not make does not
appear to have made it (REQ-006).

    dashboards/standup.py --out dashboards/site
    dashboards/standup.py --out /tmp/site --window 24

Writes standup.html and standup.json. The JSON carries `blocked_stale`,
which scripts/standup-escalate.sh reads to apply `needs-human`.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build as B  # noqa: E402  — shared parsing, CSS and escaping

REPO_ROOT = HERE.parent
BLOCKED_LABEL = "status:blocked"
STATUS_LABELS = [
    "status:needs-refinement", "status:ready", "status:in-progress",
    "status:in-review", "status:blocked",
]


def gh_json(args: list[str], default):
    try:
        out = subprocess.run(["gh", *args], cwd=REPO_ROOT, check=True,
                             capture_output=True, text=True).stdout
        return json.loads(out or "null") if out.strip() else default
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"standup: {' '.join(args[:3])} unavailable ({exc.__class__.__name__});"
              f" that section will read as empty", file=sys.stderr)
        return default


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# --------------------------------------------------------------------------
# Collection
# --------------------------------------------------------------------------

def collect_commits(since: datetime, ref: str) -> list[B.Commit]:
    raw = subprocess.run(
        ["git", "log", ref, f"--since={since.isoformat()}",
         "--format=%H%x00%s%x00%aI%x00%(trailers:only,unfold)%x01"],
        cwd=REPO_ROOT, check=True, capture_output=True, text=True).stdout
    return B.parse_commits(raw)


def collect_pulls() -> list[dict]:
    return gh_json(["pr", "list", "--state", "all", "--limit", "100", "--json",
                    "number,title,state,createdAt,mergedAt,closedAt,url,headRefName"], [])


def collect_runs() -> list[dict]:
    return gh_json(["run", "list", "--limit", "100", "--json",
                    "databaseId,name,conclusion,createdAt,headBranch,url,event"], [])


def collect_issues() -> list[dict]:
    return gh_json(["issue", "list", "--state", "all", "--limit", "200", "--json",
                    "number,title,state,labels,url,updatedAt"], [])


def collect_blocked_since(issues: list[dict], repo: str) -> dict[int, str]:
    """When did each currently-blocked issue last acquire status:blocked?

    From the issue's own `labeled` events. An agent saying "still blocked"
    is not evidence; the tracker's event log is.
    """
    out: dict[int, str] = {}
    for issue in issues:
        names = [lbl["name"] for lbl in issue.get("labels", [])]
        if BLOCKED_LABEL not in names:
            continue
        events = gh_json(["api", "--paginate",
                          f"repos/{repo}/issues/{issue['number']}/events",
                          "--jq", f'[.[] | select(.event == "labeled" and '
                                  f'.label.name == "{BLOCKED_LABEL}") | .created_at]'], [])
        if events:
            out[issue["number"]] = max(events)
    return out


# --------------------------------------------------------------------------
# The computation — pure, so it is testable without a repository
# --------------------------------------------------------------------------

def build_digest(commits, pulls, runs, issues, blocked_since, now, window_hours=24):
    """Reduce raw event data to the digest. No network, no side effects."""
    cutoff = now - timedelta(hours=window_hours)

    def recent(value: str | None) -> bool:
        dt = parse_iso(value)
        return dt is not None and dt >= cutoff

    by_role: dict[str, dict] = {}
    for commit in commits:
        entry = by_role.setdefault(commit.role, {"commits": 0, "requirements": set(),
                                                 "harnesses": set(), "subjects": []})
        entry["commits"] += 1
        entry["requirements"].update(commit.requirements)
        entry["harnesses"].add(commit.harness)
        if len(entry["subjects"]) < 5:
            entry["subjects"].append({"sha": commit.sha[:7], "subject": commit.subject})

    roles = sorted(
        ({"role": role,
          "commits": data["commits"],
          "requirements": sorted(data["requirements"]),
          "harnesses": sorted(data["harnesses"]),
          "subjects": data["subjects"]} for role, data in by_role.items()),
        key=lambda r: (-r["commits"], r["role"]),
    )

    pr_opened = [p for p in pulls if recent(p.get("createdAt"))]
    pr_merged = [p for p in pulls if recent(p.get("mergedAt"))]
    pr_closed = [p for p in pulls if recent(p.get("closedAt")) and not p.get("mergedAt")]
    pr_open_now = [p for p in pulls if p.get("state") == "OPEN"]

    failures = [r for r in runs
                if r.get("conclusion") == "failure" and recent(r.get("createdAt"))]

    board = Counter()
    for issue in issues:
        if issue.get("state") != "OPEN":
            continue
        names = [lbl["name"] for lbl in issue.get("labels", [])]
        for label in STATUS_LABELS:
            if label in names:
                board[label] += 1
        if not any(n in STATUS_LABELS for n in names):
            board["(no status)"] += 1

    needs_human = [i for i in issues
                   if i.get("state") == "OPEN"
                   and any(lbl["name"] == "needs-human" for lbl in i.get("labels", []))]

    blocked_stale = []
    for issue in issues:
        since = blocked_since.get(issue["number"])
        if not since:
            continue
        dt = parse_iso(since)
        hours = (now - dt).total_seconds() / 3600 if dt else 0
        if hours > window_hours:
            blocked_stale.append({
                "number": issue["number"], "title": issue["title"],
                "url": issue.get("url", ""), "hours": round(hours, 1),
                "since": since,
                "already_flagged": any(lbl["name"] == "needs-human"
                                       for lbl in issue.get("labels", [])),
            })
    blocked_stale.sort(key=lambda b: -b["hours"])

    return {
        "window_hours": window_hours,
        "generated_at": now.isoformat(),
        "roles": roles,
        "commits_total": len(commits),
        "pulls": {
            "opened": [_pr(p) for p in pr_opened],
            "merged": [_pr(p) for p in pr_merged],
            "closed_unmerged": [_pr(p) for p in pr_closed],
            "open_now": len(pr_open_now),
        },
        "check_failures": [{"name": r.get("name"), "branch": r.get("headBranch"),
                            "url": r.get("url"), "at": r.get("createdAt")}
                           for r in failures],
        "board": dict(board),
        "needs_human": [{"number": i["number"], "title": i["title"],
                         "url": i.get("url", "")} for i in needs_human],
        "blocked_stale": blocked_stale,
    }


def _pr(p: dict) -> dict:
    return {"number": p["number"], "title": p["title"], "url": p.get("url", ""),
            "branch": p.get("headRefName", "")}


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def render_digest_html(d: dict, meta: dict) -> str:
    e = B.esc
    w = d["window_hours"]

    def links(items):
        return "".join(
            f'<li><a href="{e(i["url"])}">#{e(i["number"])}</a> {e(i["title"][:70])}'
            f'<span class="muted mono"> {e(i.get("branch", ""))}</span></li>'
            for i in items) or '<li class="muted">none</li>'

    roles = "".join(f"""      <tr>
        <td class="req">{e(r['role'])}</td>
        <td>{r['commits']}</td>
        <td class="mono">{e(', '.join(r['requirements']) or '—')}</td>
        <td class="mono muted">{e(', '.join(r['harnesses']))}</td>
        <td><ul class="bare">{''.join(
            f'<li><span class="mono">{e(s["sha"])}</span> {e(s["subject"][:60])}</li>'
            for s in r['subjects'])}</ul></td>
      </tr>""" for r in d["roles"]) or (
        '<tr><td colspan="5" class="muted">No commits in the window. '
        'That is a fact about the window, not a status report.</td></tr>')

    board = "".join(
        f'<li><span class="mono">{e(k)}</span> — {v}</li>'
        for k, v in sorted(d["board"].items())) or '<li class="muted">no open issues</li>'

    failures = "".join(
        f'<li><a href="{e(f["url"])}">{e(f["name"])}</a> on '
        f'<span class="mono">{e(f["branch"])}</span></li>'
        for f in d["check_failures"]) or '<li class="muted">none</li>'

    stale = "".join(
        f'<li><a href="{e(b["url"])}">#{e(b["number"])}</a> {e(b["title"][:70])} — '
        f'<strong>{b["hours"]}h</strong> blocked'
        f'{" · needs-human already applied" if b["already_flagged"] else ""}</li>'
        for b in d["blocked_stale"]) or f'<li class="muted">nothing blocked beyond {w}h</li>'

    needs_human = "".join(
        f'<li><a href="{e(i["url"])}">#{e(i["number"])}</a> {e(i["title"][:70])}</li>'
        for i in d["needs_human"]) or '<li class="muted">no decisions waiting</li>'

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Standup digest — {e(meta.get('repo', ''))}</title>
<style>{B.CSS}</style>
</head><body><main>
<h1>Standup digest</h1>
<p class="sub">
  Last {w} hours, computed from commit trailers, pull request transitions,
  workflow conclusions and label history. Nobody was asked what they did —
  an agent that claims progress it did not make does not appear to have made it.
</p>

<div class="tiles">
  <div class="tile"><div class="n">{d['commits_total']}</div><div class="l">commits</div></div>
  <div class="tile"><div class="n">{len(d['pulls']['opened'])}</div><div class="l">PRs opened</div></div>
  <div class="tile"><div class="n">{len(d['pulls']['merged'])}</div><div class="l">PRs merged</div></div>
  <div class="tile"><div class="n" style="color:var(--red)">{len(d['check_failures'])}</div><div class="l">check failures</div></div>
  <div class="tile"><div class="n" style="color:var(--amber)">{len(d['blocked_stale'])}</div><div class="l">blocked &gt;{w}h</div></div>
</div>

<h2 style="font-size:1.05rem;margin:0 0 .6rem">Per-role activity</h2>
<div class="scroll"><table>
  <thead><tr><th>Role</th><th>Commits</th><th>Requirements</th><th>Harness</th><th>What landed</th></tr></thead>
  <tbody>
{roles}
  </tbody>
</table></div>

<h2 style="font-size:1.05rem;margin:2rem 0 .6rem">Needs a human decision</h2>
<ul class="bare">{needs_human}</ul>

<h2 style="font-size:1.05rem;margin:2rem 0 .6rem">Blocked beyond {w}h</h2>
<ul class="bare">{stale}</ul>
<p class="muted" style="font-size:.85rem">
  Each of these gets <span class="mono">needs-human</span> applied automatically.
  Blocked is a state with a deadline, not a resting place.
</p>

<h2 style="font-size:1.05rem;margin:2rem 0 .6rem">Pull requests</h2>
<p class="muted" style="font-size:.85rem">{d['pulls']['open_now']} open right now.</p>
<ul class="bare"><li><strong>Opened</strong></li>{links(d['pulls']['opened'])}</ul>
<ul class="bare"><li><strong>Merged</strong></li>{links(d['pulls']['merged'])}</ul>
<ul class="bare"><li><strong>Closed unmerged</strong></li>{links(d['pulls']['closed_unmerged'])}</ul>

<h2 style="font-size:1.05rem;margin:2rem 0 .6rem">Check failures</h2>
<ul class="bare">{failures}</ul>

<h2 style="font-size:1.05rem;margin:2rem 0 .6rem">Board</h2>
<ul class="bare">{board}</ul>

<footer>
  Generated {e(meta.get('generated_at', ''))} from
  <a href="{e(meta.get('repo_url', ''))}">{e(meta.get('repo', ''))}</a>.
  Event-derived (REQ-006) — no self-reported status appears on this page.
</footer>
</main></body></html>
"""


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "dashboards" / "site")
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("--repo", default="Shashank2577/foundry-program")
    ap.add_argument("--window", type=int, default=24, help="hours")
    ap.add_argument("--now", default="", help="ISO timestamp; for reproducible runs")
    args = ap.parse_args()

    now = parse_iso(args.now) if args.now else datetime.now(timezone.utc)
    since = now - timedelta(hours=args.window)

    issues = collect_issues()
    digest = build_digest(
        commits=collect_commits(since, args.ref),
        pulls=collect_pulls(),
        runs=collect_runs(),
        issues=issues,
        blocked_since=collect_blocked_since(issues, args.repo),
        now=now,
        window_hours=args.window,
    )

    meta = {
        "repo": args.repo,
        "repo_url": f"https://github.com/{args.repo}",
        "generated_at": now.strftime("%Y-%m-%d %H:%M UTC"),
    }

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "standup.html").write_text(render_digest_html(digest, meta))
    (args.out / "standup.json").write_text(json.dumps(digest, indent=2))
    B.write_page(args.out, "standup.html", "Standup digest",
                 "Per-role activity for the last 24h, derived from events")

    print(f"standup: {digest['commits_total']} commit(s) across "
          f"{len(digest['roles'])} role(s), {len(digest['pulls']['merged'])} merged, "
          f"{len(digest['check_failures'])} check failure(s), "
          f"{len(digest['blocked_stale'])} blocked >{args.window}h")
    print(f"wrote {args.out}/standup.html, standup.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
