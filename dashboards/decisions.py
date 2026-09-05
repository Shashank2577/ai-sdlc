#!/usr/bin/env python3
"""The decisions dashboard: what is waiting on a human, and what was decided.

Human-in-the-loop (REQ-007) is otherwise invisible — a held decision is a
comment on one of a hundred issues. This answers "what needs me right now"
and keeps a log of what was decided, by whom, when (REQ-011).

Classification is never reimplemented here. `scripts/gate-check.py` already
owns the critical-story rules (`matched_rules`) and the role-scoping that
narrows them to what a role could actually write (`role_can_write`, called
by `matched_rules` itself); this page imports both rather than keeping a
second copy that could disagree with the gate.

Two sections:

- Waiting on you — open `needs-human` items, open `status:needs-refinement`
  items the gate classifies critical, and open pull requests awaiting
  review. Oldest first.
- Decided — resolved holds. A decision is only logged when the `labeled`
  event actor for `status:ready` is a person; `gate-check.py --enforce`
  reads that same fact to decide whether to hold a story, so the log can't
  disagree with the gate about what counts as approval. A bot's own label
  application is never shown as a human decision.

If a reason or actor cannot be determined, the row says `unknown` — it is
never omitted and never guessed. This page describes the governance of the
system that generates it, so a flattering bug here is the worst kind.

    dashboards/decisions.py --out dashboards/site
    dashboards/decisions.py --out /tmp/site --now 2026-09-03T12:00:00Z

Writes decisions.html and decisions.json.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build as B  # noqa: E402  — shared CSS, escaping and index-linking

REPO_ROOT = HERE.parent


def _load_gate_check():
    """Import scripts/gate-check.py as a module, hyphen and all."""
    path = REPO_ROOT / "scripts" / "gate-check.py"
    spec = importlib.util.spec_from_file_location("gate_check", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("gate_check", module)
    spec.loader.exec_module(module)
    return module


G = _load_gate_check()

NEEDS_HUMAN = "needs-human"
UNREFINED = "status:needs-refinement"
READY = "status:ready"
UNKNOWN = "unknown"


# --------------------------------------------------------------------------
# Collection — talks to gh
# --------------------------------------------------------------------------

def gh_json(args: list[str], default):
    try:
        out = subprocess.run(["gh", *args], cwd=REPO_ROOT, check=True,
                             capture_output=True, text=True).stdout
        return json.loads(out or "null") if out.strip() else default
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"decisions: {' '.join(args[:3])} unavailable ({exc.__class__.__name__});"
              f" that section will read as empty", file=sys.stderr)
        return default


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def collect_issues() -> list[dict]:
    return gh_json(["issue", "list", "--state", "all", "--limit", "300", "--json",
                    "number,title,body,labels,url,createdAt,state"], [])


def collect_open_prs() -> list[dict]:
    return gh_json(["pr", "list", "--state", "open", "--limit", "100", "--json",
                    "number,title,url,createdAt,isDraft,reviewDecision,headRefName"], [])


def collect_merged_prs() -> list[dict]:
    return gh_json(["pr", "list", "--state", "merged", "--limit", "300", "--json",
                    "number,url,headRefName"], [])


def collect_label_events(number: int, repo: str) -> list[dict]:
    """`labeled`/`unlabeled` events for one issue: who, which label, when.

    The same event `gate-check.py --enforce` reads to tell a person's
    `status:ready` from an agent's — the actor on `issues: labeled`.
    """
    return gh_json([
        "api", "--paginate", f"repos/{repo}/issues/{number}/events",
        "--jq", '[.[] | select(.event=="labeled" or .event=="unlabeled") | '
                '{event, label: .label.name, actor: (.actor.login // "unknown"), '
                'created_at}]',
    ], [])


# --------------------------------------------------------------------------
# The computation — pure, so it is testable without a repository
# --------------------------------------------------------------------------

def hours_since(now: datetime, iso_ts: str | None) -> float | None:
    dt = parse_iso(iso_ts)
    return (now - dt).total_seconds() / 3600 if dt else None


def latest_event(events: list[dict], event: str, label: str) -> dict | None:
    matches = [e for e in events if e.get("event") == event and e.get("label") == label]
    return max(matches, key=lambda e: e["created_at"]) if matches else None


def _labels(issue: dict) -> list[str]:
    return [lbl["name"] for lbl in issue.get("labels", [])]


def _why(issue: dict, gate: dict):
    """Every rule the gate's own `matched_rules` trips, or `unknown`.

    `matched_rules` already calls `role_can_write` to drop rules a story's
    role could not have acted on — that scoping is not repeated here.
    """
    matches = G.matched_rules(issue.get("title", ""), issue.get("body") or "",
                              _labels(issue), gate)
    return matches or UNKNOWN


def age_hours_and_source(events: list[dict], label: str, created_at: str,
                         now: datetime) -> tuple[float, str]:
    """How long has this been waiting, and what fact says so.

    Prefers the moment the label that put it in this state was actually
    applied — the same signal the gate's own SLA check
    (`scripts/gate-sla.sh`) reads. Falls back to the issue's own creation
    time, stated as such, rather than a blank: `status.py`'s rule is that
    every number on this page names its source.
    """
    applied = latest_event(events, "labeled", label)
    if applied:
        return hours_since(now, applied["created_at"]), f"since `{label}` was applied"
    return hours_since(now, created_at), "since the issue was created (no labeled event on record)"


def waiting_rows(issues: list[dict], open_prs: list[dict],
                 events_by_issue: dict[int, list[dict]], gate: dict,
                 sla_hours: int | None, now: datetime) -> list[dict]:
    """Every open item a human needs to look at, oldest wait first."""
    rows = []
    seen = set()

    for issue in issues:
        if issue.get("state") != "OPEN" or issue["number"] in seen:
            continue
        labels = _labels(issue)
        events = events_by_issue.get(issue["number"], [])

        if NEEDS_HUMAN in labels:
            label = NEEDS_HUMAN
        elif UNREFINED in labels and G.matched_rules(
                issue.get("title", ""), issue.get("body") or "", labels, gate):
            label = UNREFINED
        else:
            continue

        seen.add(issue["number"])
        age, source = age_hours_and_source(events, label, issue.get("createdAt"), now)
        rows.append({
            "kind": "issue",
            "number": issue["number"],
            "title": issue.get("title", ""),
            "url": issue.get("url", ""),
            "why": _why(issue, gate),
            "age_hours": round(age, 1),
            "age_source": source,
            "sla_hours": sla_hours,
            "past_sla": sla_hours is not None and age > sla_hours,
        })

    for pr in open_prs:
        if pr.get("isDraft"):
            continue
        if pr.get("reviewDecision") not in (None, "", "REVIEW_REQUIRED"):
            continue
        age = hours_since(now, pr.get("createdAt")) or 0.0
        rows.append({
            "kind": "pr",
            "number": pr["number"],
            "title": pr.get("title", ""),
            "url": pr.get("url", ""),
            "why": [{"rule": "awaiting_review",
                    "because": "The `merge` gate (policies/gates.yaml) is owner: "
                               "human — an open pull request waits on a person "
                               "to review and merge it."}],
            "age_hours": round(age, 1),
            "age_source": "since the pull request was opened",
            "sla_hours": None,
            "past_sla": None,
        })

    rows.sort(key=lambda r: r["age_hours"], reverse=True)
    return rows


def decided_rows(candidates: list[dict], events_by_issue: dict[int, list[dict]],
                 pr_by_issue: dict[int, dict], gate: dict) -> list[dict]:
    """The resolution log: a `status:ready` labeled event applied by a person.

    Reads the same fact `gate-check.py --enforce` reads to approve a
    critical story, so this log cannot show an approval the gate itself
    would not have honoured. A bot's own label application never appears
    here as a human decision — the row is dropped, not attributed to
    `unknown`, because "somebody decided this, we just don't know who"
    would be false: nobody did.
    """
    rows = []
    for issue in candidates:
        events = events_by_issue.get(issue["number"], [])
        event = latest_event(events, "labeled", READY)
        if not event:
            continue
        actor = event.get("actor", UNKNOWN)
        if not G.is_human(actor):
            continue
        artefact = pr_by_issue.get(issue["number"]) or {
            "url": issue.get("url", ""), "label": f"issue #{issue['number']}",
        }
        rows.append({
            "number": issue["number"],
            "title": issue.get("title", ""),
            "url": issue.get("url", ""),
            "decision": f"Approved to proceed (`{READY}`)",
            "by": actor,
            "when": event["created_at"],
            "why": _why(issue, gate),
            "artefact": artefact,
        })
    rows.sort(key=lambda r: r["when"], reverse=True)
    return rows


def pr_by_issue_number(merged_prs: list[dict]) -> dict[int, dict]:
    """Map an issue number to the merged PR that carried its branch, if any.

    Same branch-name convention `status.py` reads to measure self-hosting:
    `story/FDY-<n>-...` or `bug/FDY-<n>-...`.
    """
    out = {}
    for pr in merged_prs:
        m = re.match(r"^(?:story|bug)/FDY-(\d+)-", pr.get("headRefName", ""))
        if m:
            out[int(m.group(1))] = {"url": pr.get("url", ""),
                                    "label": f"PR #{pr['number']}"}
    return out


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def render_why(e, why) -> str:
    if why == UNKNOWN or not why:
        return '<span class="muted">unknown</span>'
    return "".join(
        f'<div><strong>{e(w["rule"])}</strong> — {e(w["hit"]) if "hit" in w else ""} '
        f'{e(w["because"])}</div>'
        for w in why
    )


def render(report: dict, meta: dict) -> str:
    e = B.esc
    w = report["waiting"]
    d = report["decided"]

    def waiting_row_html(r):
        cls = " pastsla" if r["past_sla"] else ""
        sla_note = ""
        if r["sla_hours"] is not None:
            sla_note = (f' <span class="pill red">past {r["sla_hours"]}h SLA</span>'
                       if r["past_sla"] else
                       f' <span class="muted">(SLA {r["sla_hours"]}h)</span>')
        kind_label = "PR" if r["kind"] == "pr" else "#"
        return f"""      <tr class="{cls.strip()}">
        <td><a href="{e(r['url'])}">{kind_label}{e(r['number'])}</a> {e(r['title'][:70])}</td>
        <td>{render_why(e, r['why'])}</td>
        <td class="mono">{r['age_hours']}h{sla_note}<br>
            <span class="muted" style="font-size:.8em">{e(r['age_source'])}</span></td>
      </tr>"""

    waiting_html = "".join(waiting_row_html(r) for r in w) or (
        '<tr><td colspan="3" class="muted">Nothing is waiting on a human right now.</td></tr>')

    def decided_row_html(r):
        return f"""      <tr>
        <td><a href="{e(r['url'])}">#{e(r['number'])}</a> {e(r['title'][:70])}</td>
        <td>{e(r['decision'])}<br>{render_why(e, r['why'])}</td>
        <td>{e(r['by'])}</td>
        <td class="mono">{e(r['when'])}</td>
        <td><a href="{e(r['artefact']['url'])}">{e(r['artefact']['label'])}</a></td>
      </tr>"""

    decided_html = "".join(decided_row_html(r) for r in d) or (
        '<tr><td colspan="5" class="muted">No resolved holds yet.</td></tr>')

    waiting_count = len(w)
    past_sla_count = sum(1 for r in w if r["past_sla"])

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Decisions — {e(meta.get('repo', ''))}</title>
<style>{B.CSS}
tr.pastsla {{ background: var(--red-bg) }}
</style>
</head><body><main>
<h1>Decisions</h1>
<p class="sub">
  What is waiting on a human, and what was decided, computed from open
  <span class="mono">needs-human</span> and <span class="mono">status:needs-refinement</span>
  items the gate classifies critical (<span class="mono">scripts/gate-check.py</span>),
  open pull requests, and the <span class="mono">status:ready</span> label events that
  <span class="mono">gate-check.py --enforce</span> itself reads as approval. A reason or
  actor this page cannot determine is shown as <span class="mono">unknown</span> —
  never omitted, never guessed.
</p>

<div class="tiles">
  <div class="tile"><div class="n">{waiting_count}</div><div class="l">waiting on you</div></div>
  <div class="tile"><div class="n" style="color:var(--red)">{past_sla_count}</div><div class="l">past SLA</div></div>
  <div class="tile"><div class="n">{len(d)}</div><div class="l">decided</div></div>
</div>

<h2 style="font-size:1.05rem;margin:0 0 .6rem">Waiting on you</h2>
<p class="muted" style="font-size:.85rem">Oldest wait first.</p>
<div class="scroll"><table>
  <thead><tr><th>Item</th><th>Why</th><th>Waiting</th></tr></thead>
  <tbody>
{waiting_html}
  </tbody>
</table></div>

<h2 style="font-size:1.05rem;margin:2rem 0 .6rem">Decided</h2>
<p class="muted" style="font-size:.85rem">
  Attributed to the actor on the <span class="mono">status:ready</span> label event —
  the same fact the gate reads. A bot applying that label is never shown here.
</p>
<div class="scroll"><table>
  <thead><tr><th>Item</th><th>Decision &amp; why held</th><th>By</th><th>When</th><th>Artefact</th></tr></thead>
  <tbody>
{decided_html}
  </tbody>
</table></div>

<footer>
  Generated {e(meta.get('generated_at', ''))} from
  <a href="{e(meta.get('repo_url', ''))}">{e(meta.get('repo', ''))}</a>, reading
  <span class="mono">policies/gates.yaml</span> (SLA {e(str(meta.get('sla_hours', UNKNOWN)))}h)
  and <span class="mono">scripts/gate-check.py</span> for classification.
</footer>
</main></body></html>
"""


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "dashboards" / "site")
    ap.add_argument("--ref", default="HEAD", help="unused; kept for CLI parity with the other generators")
    ap.add_argument("--repo", default="Shashank2577/ai-sdlc")
    ap.add_argument("--now", default="", help="ISO timestamp; for reproducible runs")
    args = ap.parse_args()

    now = parse_iso(args.now) if args.now else datetime.now(timezone.utc)
    gate = G.load_gate()
    sla_hours = gate.get("sla_hours")

    issues = collect_issues()
    open_prs = collect_open_prs()
    merged_prs = collect_merged_prs()
    pr_by_issue = pr_by_issue_number(merged_prs)

    decided_candidates = [i for i in issues
                          if i.get("state") == "CLOSED" or READY in _labels(i)]

    needed = set()
    for issue in issues:
        labels = _labels(issue)
        if NEEDS_HUMAN in labels or (UNREFINED in labels and G.matched_rules(
                issue.get("title", ""), issue.get("body") or "", labels, gate)):
            needed.add(issue["number"])
    needed.update(i["number"] for i in decided_candidates)

    events_by_issue = {n: collect_label_events(n, args.repo) for n in needed}

    report = {
        "waiting": waiting_rows(issues, open_prs, events_by_issue, gate, sla_hours, now),
        "decided": decided_rows(decided_candidates, events_by_issue, pr_by_issue, gate),
    }

    meta = {
        "repo": args.repo,
        "repo_url": f"https://github.com/{args.repo}",
        "generated_at": now.strftime("%Y-%m-%d %H:%M UTC"),
        "sla_hours": sla_hours,
    }

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "decisions.html").write_text(render(report, meta))
    (args.out / "decisions.json").write_text(json.dumps({"meta": meta, **report}, indent=2))
    B.write_page(args.out, "decisions.html", "Decisions",
                 "What's waiting on a human, and what was decided")

    past_sla = sum(1 for r in report["waiting"] if r["past_sla"])
    print(f"decisions: {len(report['waiting'])} waiting on a human "
          f"({past_sla} past SLA), {len(report['decided'])} decided")
    print(f"wrote {args.out}/decisions.html, decisions.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
