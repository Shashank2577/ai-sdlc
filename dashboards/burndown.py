#!/usr/bin/env python3
"""Build the burndown and velocity dashboard — computed from the tracker's
own event log, never self-reported.

This repository has no story-point system, so both metrics are counts of
`type:story` issues rather than points. `type:bug` and `type:task` issues
are deliberately excluded: burndown and velocity describe committed story
scope, not the whole issue tracker (REQ-011).

Burndown is the count of open stories at each day boundary across the
window — a story is open at a boundary if it existed by then (`createdAt`)
and had not yet closed (`closedAt`) as of that boundary. It is computed
fresh at every boundary from those two timestamps, not a live snapshot of
"open now" repeated across days — so it is accurate for the whole window
even when run once, today.

Velocity is the count of stories whose `closedAt` falls inside each
weekly bucket of the window (oldest-first, buckets `(start, end]` so a
closure lands in exactly one bucket even when it lands on a boundary).

    dashboards/burndown.py --out dashboards/site
    dashboards/burndown.py --out /tmp/site --window 30

Writes burndown.html and burndown.json.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build as B  # noqa: E402  — shared CSS, escaping and index-linking

REPO_ROOT = HERE.parent
STORY_LABEL = "type:story"


def gh_json(args: list[str], default):
    try:
        out = subprocess.run(["gh", *args], cwd=REPO_ROOT, check=True,
                             capture_output=True, text=True).stdout
        return json.loads(out or "null") if out.strip() else default
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"burndown: {' '.join(args[:3])} unavailable ({exc.__class__.__name__});"
              f" that section will read as empty", file=sys.stderr)
        return default


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def collect_issues() -> list[dict]:
    return gh_json(["issue", "list", "--state", "all", "--limit", "500", "--json",
                    "number,createdAt,closedAt,labels"], [])


def is_story(issue: dict) -> bool:
    return any(lbl["name"] == STORY_LABEL for lbl in issue.get("labels", []))


# --------------------------------------------------------------------------
# The computation — pure, so it is testable without a repository
# --------------------------------------------------------------------------

def day_boundaries(now: datetime, window_days: int) -> list[datetime]:
    """One boundary per day, oldest first, ending at `now`."""
    return [now - timedelta(days=offset) for offset in range(window_days, -1, -1)]


def week_buckets(now: datetime, window_days: int) -> list[tuple[datetime, datetime]]:
    """Weekly `(start, end]` buckets covering the window, oldest first,
    ending at `now`. Buckets partition the window exactly once each, so a
    closure on a bucket edge is never double-counted or dropped."""
    start_of_window = now - timedelta(days=window_days)
    buckets = []
    cursor = start_of_window
    while cursor < now:
        end = min(cursor + timedelta(days=7), now)
        buckets.append((cursor, end))
        cursor = end
    return buckets or [(start_of_window, now)]


def build_report(issues: list[dict], now: datetime, window_days: int = 60) -> dict:
    """Reduce raw issue data to the report. No network, no side effects."""
    stories = [i for i in issues if is_story(i)]

    burndown = []
    for boundary in day_boundaries(now, window_days):
        open_count = 0
        for story in stories:
            created = parse_iso(story.get("createdAt"))
            closed = parse_iso(story.get("closedAt"))
            if created is None or created > boundary:
                continue
            if closed is not None and closed <= boundary:
                continue
            open_count += 1
        burndown.append({"date": boundary.strftime("%Y-%m-%d"), "open": open_count})

    velocity = []
    for start, end in week_buckets(now, window_days):
        closed_count = sum(
            1 for s in stories
            if (closed := parse_iso(s.get("closedAt"))) is not None and start < closed <= end
        )
        velocity.append({"week_start": start.strftime("%Y-%m-%d"),
                         "week_end": end.strftime("%Y-%m-%d"), "closed": closed_count})

    return {
        "window_days": window_days,
        "generated_at": now.isoformat(),
        "story_count": len(stories),
        "burndown": burndown,
        "velocity": velocity,
    }


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def bar(value: int, max_value: int, colour: str) -> str:
    pct = round(100 * value / max_value) if max_value else 0
    return (f'<div style="background:var(--line);border-radius:99px;height:7px;'
            f'min-width:70px"><div style="width:{pct}%;background:{colour};'
            f'height:7px;border-radius:99px"></div></div>')


def render(r: dict, meta: dict) -> str:
    e = B.esc
    max_open = max((p["open"] for p in r["burndown"]), default=0)
    max_closed = max((w["closed"] for w in r["velocity"]), default=0)

    burndown_rows = "".join(f"""      <tr>
        <td class="mono">{e(p['date'])}</td>
        <td>{p['open']}</td>
        <td style="min-width:110px">{bar(p['open'], max_open, 'var(--amber)')}</td>
      </tr>""" for p in r["burndown"]) or (
        '<tr><td colspan="3" class="muted">No day boundaries in the window.</td></tr>')

    velocity_rows = "".join(f"""      <tr>
        <td class="mono">{e(w['week_start'])} – {e(w['week_end'])}</td>
        <td>{w['closed']}</td>
        <td style="min-width:110px">{bar(w['closed'], max_closed, 'var(--green)')}</td>
      </tr>""" for w in r["velocity"]) or (
        '<tr><td colspan="3" class="muted">No weekly buckets in the window.</td></tr>')

    open_now = r["burndown"][-1]["open"] if r["burndown"] else 0
    last_week_closed = r["velocity"][-1]["closed"] if r["velocity"] else 0

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Burndown &amp; velocity — {e(meta.get('repo', ''))}</title>
<style>{B.CSS}</style>
</head><body><main>
<h1>Burndown &amp; velocity</h1>
<p class="sub">
  Last {r['window_days']} days, computed from <span class="mono">type:story</span>
  issue timestamps — no story-point system exists yet, so both metrics are
  issue counts. <span class="mono">type:bug</span> and <span class="mono">type:task</span>
  issues are excluded: this is about committed story scope, not the whole tracker.
</p>

<div class="tiles">
  <div class="tile"><div class="n">{r['story_count']}</div><div class="l">stories tracked</div></div>
  <div class="tile"><div class="n" style="color:var(--amber)">{open_now}</div><div class="l">open now</div></div>
  <div class="tile"><div class="n" style="color:var(--green)">{last_week_closed}</div><div class="l">closed last week</div></div>
</div>

<h2 style="font-size:1.05rem;margin:0 0 .6rem">Burndown — open stories at each day boundary</h2>
<div class="scroll"><table>
  <thead><tr><th>Date</th><th>Open</th><th></th></tr></thead>
  <tbody>
{burndown_rows}
  </tbody>
</table></div>

<h2 style="font-size:1.05rem;margin:2rem 0 .6rem">Velocity — stories closed per week</h2>
<div class="scroll"><table>
  <thead><tr><th>Week</th><th>Closed</th><th></th></tr></thead>
  <tbody>
{velocity_rows}
  </tbody>
</table></div>

<footer>
  Generated {e(meta.get('generated_at', ''))} from
  <a href="{e(meta.get('repo_url', ''))}">{e(meta.get('repo', ''))}</a>.
  Computed from issue timestamps — nobody was asked what shipped.
</footer>
</main></body></html>
"""


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "dashboards" / "site")
    ap.add_argument("--repo", default="Shashank2577/foundry-program")
    ap.add_argument("--window", type=int, default=60, help="days")
    ap.add_argument("--now", default="", help="ISO timestamp; for reproducible runs")
    args = ap.parse_args()

    now = parse_iso(args.now) if args.now else datetime.now(timezone.utc)

    report = build_report(collect_issues(), now=now, window_days=args.window)

    meta = {
        "repo": args.repo,
        "repo_url": f"https://github.com/{args.repo}",
        "generated_at": now.strftime("%Y-%m-%d %H:%M UTC"),
    }

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "burndown.html").write_text(render(report, meta))
    (args.out / "burndown.json").write_text(json.dumps(report, indent=2))
    B.write_page(args.out, "burndown.html", "Burndown & velocity",
                 "Open story count and weekly closures, from issue timestamps")

    open_now = report["burndown"][-1]["open"] if report["burndown"] else 0
    last_week = report["velocity"][-1]["closed"] if report["velocity"] else 0
    print(f"burndown: {report['story_count']} stor(y/ies) tracked, "
          f"{open_now} open now, {last_week} closed in the last week")
    print(f"wrote {args.out}/burndown.html, burndown.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
