#!/usr/bin/env python3
"""Build the QA verdict dashboard: a pass/fail matrix, grouped by requirement.

REQ-009's veto is already enforced by `scripts/qa-gate.sh` and
`scripts/qa-verdict.sh` — this generator answers the part that was still
missing, the published half. For every REQ marker (`→ **REQ-00N**`) found on
an issue, every issue carrying that requirement is listed as `approved`,
`rejected` or `pending`, computed from the `qa:approved` / `qa:rejected`
labels QA's own policy already uses. Nobody is asked for a verdict; the
label is the verdict.

    dashboards/qa.py --out dashboards/site
    dashboards/qa.py --out /tmp/site --now 2026-09-02T12:00:00+00:00

Writes qa.html and qa.json. This generator reads nothing but
`gh issue list`, so unlike the standup digest or the status page it depends
on no other generator's output and can run in any order relative to them.

PRD §8 also names a coverage trend, defect density and a flake list for
this report. All three need escaped-defect tracking and CI flake history
that don't exist as computable inputs yet — this generator does not
fabricate placeholder numbers for them. A per-sprint cut is likewise out of
scope: there is no populated sprint field to group by yet.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build as B  # noqa: E402  — shared CSS and escaping

REPO_ROOT = HERE.parent

# The REQ-marker parse belongs to scripts/sync-project.py — reused here
# rather than reimplemented, so this stays the third dashboard sharing one
# regex instead of the third dashboard defining its own.
_spec = importlib.util.spec_from_file_location(
    "sync_project", REPO_ROOT / "scripts" / "sync-project.py")
SP = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SP)
REQ = SP.REQ
REQ_MARKER = SP.REQ_MARKER

APPROVED, REJECTED, PENDING = "approved", "rejected", "pending"


def gh_json(args: list[str], default):
    try:
        out = subprocess.run(["gh", *args], cwd=REPO_ROOT, check=True,
                             capture_output=True, text=True).stdout
        return json.loads(out) if out.strip() else default
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"qa: gh {' '.join(args[:3])} unavailable ({exc.__class__.__name__});"
              " the matrix will read as empty", file=sys.stderr)
        return default


def collect_issues() -> list[dict]:
    return gh_json(["issue", "list", "--state", "all", "--limit", "200", "--json",
                    "number,title,state,labels,body,closedAt"], [])


# --------------------------------------------------------------------------
# The computation — pure, so it is testable without a repository
# --------------------------------------------------------------------------

def issue_requirements(body: str | None) -> list[str]:
    """REQ ids from a story's `→ **REQ-00N**` marker, and only that marker.

    sync-project.py falls back to scraping the whole body when the marker
    is absent, because a board field defaulting to blank is harmless. A QA
    verdict is not harmless the same way: scraping acceptance-criteria text
    would attribute a pass or fail to a requirement nobody actually claimed
    the issue serves. No marker means excluded, not guessed.
    """
    m = REQ_MARKER.search(body or "")
    return sorted(set(REQ.findall(m.group(1)))) if m else []


def verdict(issue: dict) -> str:
    """Rejected outranks approved — the same precedence as the QA policy's
    own veto (a rejected item cannot close no matter what else is true)."""
    names = {lbl["name"] for lbl in issue.get("labels", [])}
    if "qa:rejected" in names:
        return REJECTED
    if "qa:approved" in names:
        return APPROVED
    return PENDING


def build_matrix(issues: list[dict]) -> dict[str, list[dict]]:
    """REQ -> issues carrying it, each marked approved/rejected/pending.

    A rejected issue is never dropped for failing — omitting a failure is
    exactly the thing a published verdict page exists to prevent.
    """
    matrix: dict[str, list[dict]] = {}
    for issue in issues:
        reqs = issue_requirements(issue.get("body"))
        if not reqs:
            continue
        entry = {
            "number": issue["number"],
            "title": issue["title"],
            "state": issue.get("state", "OPEN"),
            "verdict": verdict(issue),
        }
        for req in reqs:
            matrix.setdefault(req, []).append(entry)
    for entries in matrix.values():
        entries.sort(key=lambda e: e["number"])
    return matrix


def req_status(entries: list[dict]) -> str:
    """One-word rollup for a requirement's row: a single rejected issue
    fails the row regardless of how many siblings passed; a still-pending
    issue keeps the row pending rather than calling it approved early."""
    verdicts = {e["verdict"] for e in entries}
    if REJECTED in verdicts:
        return REJECTED
    if PENDING in verdicts:
        return PENDING
    return APPROVED


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

PILL_CLASS = {APPROVED: "green", REJECTED: "red", PENDING: "amber"}


def render_html(matrix: dict[str, list[dict]], meta: dict) -> str:
    e = B.esc
    repo_url = meta.get("repo_url", "")

    counts = Counter(entry["verdict"] for entries in matrix.values() for entry in entries)

    rows = []
    for req in sorted(matrix):
        entries = matrix[req]
        status = req_status(entries)
        items = "".join(
            f'<li><span class="pill {PILL_CLASS[it["verdict"]]}">{it["verdict"]}</span> '
            f'<a href="{e(repo_url)}/issues/{e(it["number"])}">#{e(it["number"])}</a> '
            f'{e(it["title"][:70])}</li>'
            for it in entries)
        rows.append(f"""      <tr>
        <td class="req">{e(req)}</td>
        <td><span class="pill {PILL_CLASS[status]}">{status}</span></td>
        <td><ul class="bare">{items}</ul></td>
      </tr>""")
    rows_html = "\n".join(rows) or (
        '<tr><td colspan="3" class="muted">No issue carries a REQ marker with a '
        'QA verdict yet.</td></tr>')

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>QA verdicts — {e(meta.get('repo', ''))}</title>
<style>{B.CSS}</style>
</head><body><main>
<h1>QA verdicts</h1>
<p class="sub">
  Pass/fail, grouped by requirement. Computed from the <code>qa:approved</code> /
  <code>qa:rejected</code> labels on issues carrying a
  <code>→ **REQ-00N**</code> marker — the same labels QA's own veto
  (<code>scripts/qa-gate.sh</code>, <code>scripts/qa-verdict.sh</code>) already
  enforces. Nobody is asked for a verdict; the label is the verdict.
</p>

<div class="tiles">
  <div class="tile"><div class="n">{len(matrix)}</div><div class="l">requirements</div></div>
  <div class="tile"><div class="n" style="color:var(--green)">{counts[APPROVED]}</div><div class="l">approved</div></div>
  <div class="tile"><div class="n" style="color:var(--red)">{counts[REJECTED]}</div><div class="l">rejected</div></div>
  <div class="tile"><div class="n" style="color:var(--amber)">{counts[PENDING]}</div><div class="l">pending</div></div>
</div>

<div class="scroll"><table>
  <thead><tr><th>REQ</th><th>Status</th><th>Issues</th></tr></thead>
  <tbody>
{rows_html}
  </tbody>
</table></div>

<p class="sub" style="margin-top:2rem">
  Out of scope here (PRD §8): coverage trend, defect density and a flake
  list all need escaped-defect tracking and CI flake history that do not
  exist as computable inputs yet. A per-sprint cut is likewise out of scope —
  there is no populated sprint field to group by.
</p>

<footer>
  Generated {e(meta.get('generated_at', ''))} from
  <a href="{e(repo_url)}">{e(meta.get('repo', ''))}</a>.
</footer>
</main></body></html>
"""


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "dashboards" / "site")
    ap.add_argument("--repo", default="Shashank2577/foundry-program")
    ap.add_argument("--now", default="", help="ISO timestamp; for reproducible runs")
    args = ap.parse_args()

    now = (datetime.fromisoformat(args.now.replace("Z", "+00:00"))
           if args.now else datetime.now(timezone.utc))

    matrix = build_matrix(collect_issues())
    meta = {
        "repo": args.repo,
        "repo_url": f"https://github.com/{args.repo}",
        "generated_at": now.strftime("%Y-%m-%d %H:%M UTC"),
    }

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "qa.html").write_text(render_html(matrix, meta))
    (args.out / "qa.json").write_text(json.dumps({"meta": meta, "matrix": matrix}, indent=2))
    B.write_page(args.out, "qa.html", "QA verdicts",
                 "Pass/fail matrix by requirement, from qa:approved/qa:rejected")

    counts = Counter(entry["verdict"] for entries in matrix.values() for entry in entries)
    print(f"qa: {len(matrix)} requirement(s) with a verdict — "
          f"{counts[APPROVED]} approved, {counts[REJECTED]} rejected, "
          f"{counts[PENDING]} pending")
    print(f"wrote {args.out}/qa.html, qa.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
