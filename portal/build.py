#!/usr/bin/env python3
"""Build the client portal: what was delivered, what needs a decision.

The audience is a paying client, not an engineer (#117, REQ-008 / REQ-011).
Nothing here is authored by hand — every figure is computed from the same
sources the engineering dashboards already use, loaded directly rather than
re-derived so the two can never quietly disagree:

  - delivered work        dashboards/build.py's commit -> merged-PR join,
                           keyed by the `Work-Item:` trailer instead of
                           `Requirement:` — a trailer alone proves nothing;
                           a merged PR behind it is GitHub's own record.
  - requirement figures    dashboards/status.py's evaluate() against
                           requirements/coverage.yaml. That is the computed
                           satisfaction score, never the trailer trace alone
                           — two earlier proxies (a policy file merely
                           existing, a declaration with no workflow behind
                           it) were rejected for flattering the programme,
                           and a client-facing page is the worst place to
                           repeat that mistake.
  - sign-off state         scripts/signoff-check.py's classify(), reused
                           rather than reimplemented, so bot-actor
                           rejection can never drift between the two.
                           policies/signoff.yaml supplies the vocabulary
                           for what a scope needs (its question, its
                           evidence, its default) rather than this file
                           inventing a second one.

Honesty rules this page exists to hold (see the work item):
  - a state this cannot positively confirm is reported as `not yet
    reviewed`, never as accepted
  - no label name, branch name or bare REQ id reaches reader-facing text
  - every figure states the date and the source it was computed from

    portal/build.py --out portal/site
    portal/build.py --out /tmp/site --no-github   # nothing can be
                                                    # confirmed delivered
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent


def _load(name: str, relpath: str):
    """Load a sibling script by path — the repo's own idiom for reusing a
    module whose filename cannot be `import`ed (dashes) or that lives
    outside this package (dashboards/, scripts/)."""
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / relpath)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses in the loaded module need this to resolve
    spec.loader.exec_module(module)
    return module


B = _load("portal_dash_build", "dashboards/build.py")          # CSS, esc, write_page, commit/PR join
STATUS = _load("portal_dash_status", "dashboards/status.py")   # coverage evaluate()
SC = _load("portal_signoff_check", "scripts/signoff-check.py")  # classify(), policy
SP = _load("portal_sync_project", "scripts/sync-project.py")    # REQ marker regex

esc = B.esc

WORK_ITEM_ISSUE = re.compile(r"#(\d+)\s*$")

# Change requests, per policies/signoff.yaml's `change_request.filed_by`:
# "an issue labeled `type:change-request` referencing the signed scope",
# plus the label the signed-scope side wears once one is granted.
CR_LABELS = {"type:change-request", "signoff:change-requested"}

# status:* -> plain language, without the label name. Order matches
# scripts/sync-project.py's own STATUS_BY_LABEL precedence, so an item
# carrying more than one status label resolves to the same phrase a
# maintainer would get from the board.
IN_PROGRESS_PLAIN = [
    ("status:blocked", "waiting on a decision"),
    ("status:in-review", "finished and being checked before it counts as delivered"),
    ("status:in-progress", "being worked on right now"),
    ("status:ready", "queued to start"),
    ("status:needs-refinement", "being scoped out before work starts"),
]

# Only the evidence lines that actually appear in policies/signoff.yaml's
# `story` scope today. An evidence line this repo's policy doesn't say yet
# has no plain translation to invent — see plain_evidence() — so it falls
# back rather than guessing at wording nobody wrote.
EVIDENCE_PLAIN = {
    "qa:approved label present (the qa verdict, prd §8)":
        "it passed quality review",
    "the dod required check is green on the merged pr (policies/dod.yaml)":
        "it passed the project's required checks",
    "the linked work item is closed":
        "the task tracking it is finished",
}


def plain_evidence(raw: str) -> str:
    return EVIDENCE_PLAIN.get(raw.strip().lower(), "an internal check")


def plain_title(title: str) -> str:
    """Strip a ticket-code prefix (`P2-5:`, `BUG:`) a client has no reason
    to parse, and redact any bare REQ id mentioned inline — some issue
    titles name one in passing ("...settle REQ-002"), and the honesty rule
    is "no bare REQ id in reader-facing text", not "only in the prefix"."""
    title = re.sub(r"^\s*[A-Za-z]+\d*-\d+:\s*", "", title)
    title = re.sub(r"^\s*BUG:\s*", "", title, flags=re.IGNORECASE)
    title = SP.REQ.sub("a requirement", title)
    # A title can also mention a label verbatim in passing ("...the guard
    # requires status:ready"), not only carry one as metadata — the rule
    # is no label name in reader-facing text, wherever it appears.
    title = re.sub(r"\b(?:status|qa|signoff|type|role):[a-z][a-z-]*\b",
                   "an internal marker", title, flags=re.IGNORECASE)
    return title.strip()


def parse_work_item_issue(trailer_value: str) -> int | None:
    """`owner/repo#123` -> 123, whichever repo the trailer names."""
    m = WORK_ITEM_ISSUE.search(trailer_value or "")
    return int(m.group(1)) if m else None


def issue_requirements(body: str | None) -> list[str]:
    """REQ ids from a story's `→ **REQ-00N**` marker, and only that marker
    — the same rule dashboards/qa.py applies, so a requirement is never
    attributed from text mentioned only in passing."""
    m = SP.REQ_MARKER.search(body or "")
    return sorted(set(SP.REQ.findall(m.group(1)))) if m else []


# --------------------------------------------------------------------------
# Delivered work — a merged PR behind a Work-Item trailer, never the
# trailer alone.
# --------------------------------------------------------------------------

def delivered_issue_numbers(commits: list, pulls_for_sha: dict) -> dict[int, dict]:
    """issue -> {pr_number, pr_url} for every Work-Item whose commit reached
    main through an actual merged PR — GitHub's own commits/pulls record,
    not a trailer's say-so."""
    out: dict[int, dict] = {}
    for commit in commits:
        issue = parse_work_item_issue(commit.trailers.get("Work-Item", ""))
        if issue is None:
            continue
        for pr in pulls_for_sha.get(commit.sha, []):
            out.setdefault(issue, {"pr_number": pr["number"], "pr_url": pr["url"]})
    return out


def signoff_display(state: str, policy: dict, scope: str = "story") -> tuple[str, list[str]]:
    """Plain-language sign-off state and the evidence behind it, read from
    policies/signoff.yaml's own scope vocabulary rather than a second,
    hardcoded one. `not yet reviewed` is the only answer for a state this
    cannot positively confirm — never optimistic, never blank."""
    scope_policy = (policy.get("signoffs") or {}).get(scope, {})
    evidence = [plain_evidence(e) for e in (scope_policy.get("evidence_required") or [])]

    if state == SC.STATE_SIGNED:
        return "signed off — you accepted this as delivered", evidence
    if state == SC.STATE_CHANGE_REQUESTED:
        return "reopened by a change request", evidence
    if state == SC.STATE_UNSIGNED:
        return "awaiting your sign-off", evidence
    # SC.STATE_UNDETERMINED, or any future state this page doesn't
    # recognise: never imply acceptance for a state it can't confirm.
    return "not yet reviewed", evidence


@dataclass
class Delivered:
    issue: int
    title: str
    pr_number: int
    pr_url: str
    requirements: list[str] = field(default_factory=list)  # internal only, never rendered bare
    requirement_label: str = "General delivery"
    signoff_text: str = "not yet reviewed"
    evidence: list[str] = field(default_factory=list)
    needs_signoff: bool = True


def requirement_label(reqs: list[str], coverage: dict) -> str:
    if not reqs:
        return "General delivery"
    return coverage.get(reqs[0], {}).get("summary") or "General delivery"


def build_delivered(issues_by_number: dict, delivered_map: dict, coverage: dict,
                     policy: dict, fetch_events) -> list[Delivered]:
    out = []
    for issue_no, pr in delivered_map.items():
        issue = issues_by_number.get(issue_no)
        if issue is None:
            continue
        reqs = issue_requirements(issue.get("body"))
        labels = [lbl["name"] for lbl in issue.get("labels", [])]
        events = fetch_events(issue_no)
        state, _detail = SC.classify(labels, events)
        text, evidence = signoff_display(state, policy)
        out.append(Delivered(
            issue=issue_no,
            title=plain_title(issue["title"]),
            pr_number=pr["pr_number"],
            pr_url=pr["pr_url"],
            requirements=reqs,
            requirement_label=requirement_label(reqs, coverage),
            signoff_text=text,
            evidence=evidence,
            needs_signoff=state != SC.STATE_SIGNED,
        ))
    out.sort(key=lambda d: d.issue)
    return out


def group_by_requirement(delivered: list[Delivered]) -> list[tuple[str, list[Delivered]]]:
    groups: dict[str, list[Delivered]] = {}
    for d in delivered:
        groups.setdefault(d.requirement_label, []).append(d)
    return sorted(groups.items(), key=lambda kv: kv[0])


# --------------------------------------------------------------------------
# Open change requests and in-progress work — issue state and labels only.
# --------------------------------------------------------------------------

@dataclass
class ChangeRequest:
    issue: int
    title: str


def build_change_requests(issues: list[dict]) -> list[ChangeRequest]:
    out = []
    for issue in issues:
        if issue.get("state") != "OPEN":
            continue
        labels = {lbl["name"] for lbl in issue.get("labels", [])}
        if labels & CR_LABELS:
            out.append(ChangeRequest(issue=issue["number"], title=plain_title(issue["title"])))
    out.sort(key=lambda c: c.issue)
    return out


@dataclass
class InProgress:
    issue: int
    title: str
    plain_status: str


def build_in_progress(issues: list[dict], exclude: set[int]) -> list[InProgress]:
    out = []
    for issue in issues:
        if issue.get("state") != "OPEN" or issue["number"] in exclude:
            continue
        labels = {lbl["name"] for lbl in issue.get("labels", [])}
        if labels & CR_LABELS:
            continue
        plain = next((p for lbl, p in IN_PROGRESS_PLAIN if lbl in labels), "in progress")
        out.append(InProgress(issue=issue["number"], title=plain_title(issue["title"]),
                               plain_status=plain))
    out.sort(key=lambda i: i.issue)
    return out


# --------------------------------------------------------------------------
# The world — gh and git, isolated so tests never call either.
# --------------------------------------------------------------------------

def gh_json(args: list[str], default):
    try:
        out = subprocess.run(["gh", *args], cwd=REPO_ROOT, check=True,
                             capture_output=True, text=True).stdout
        return json.loads(out) if out.strip() else default
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"portal: gh {' '.join(args[:3])} unavailable ({exc.__class__.__name__}); "
              "issue-derived sections will read as empty", file=sys.stderr)
        return default


def collect_issues() -> list[dict]:
    return gh_json(["issue", "list", "--state", "all", "--limit", "300", "--json",
                    "number,title,state,labels,body"], [])


def fetch_events_safely(issue_no: int) -> list[dict]:
    try:
        return SC.fetch_label_events(issue_no)
    except subprocess.CalledProcessError:
        return []


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

EXTRA_CSS = """
.section { margin: 2.5rem 0 }
.card { border:1px solid var(--line); border-radius:8px; padding:1rem 1.2rem;
  background:var(--card); margin-bottom:.9rem }
.card h3 { margin:0 0 .3rem; font-size:1rem }
.card .meta { color:var(--muted); font-size:.85rem; margin:.2rem 0 }
.badge { display:inline-block; padding:.1rem .55rem; border-radius:99px;
  font-size:.78rem; font-weight:600; background:var(--amber-bg); color:var(--amber) }
.badge.ok { background:var(--green-bg); color:var(--green) }
ul.evidence { margin:.4rem 0 0; padding-left:1.2rem; font-size:.85rem; color:var(--muted) }
.empty { color:var(--muted); font-style:italic }
"""


def render_delivered_group(label: str, items: list, coverage: dict, meta: dict) -> str:
    e = B.esc
    req = items[0].requirements[0] if items[0].requirements else None
    cov = coverage.get(req) if req else None
    cov_line = ""
    if cov:
        cov_line = (
            f'<p class="meta">Verified as actually built: {cov["passed"]}/{cov["total"]} '
            f'checks pass ({cov["pct"]}%), computed {e(meta.get("generated_at",""))} from '
            f'<code>requirements/coverage.yaml</code> — '
            f'<a href="status.html">see how</a>.</p>'
        )
    cards = "\n".join(f"""    <div class="card">
      <h3>{e(item.title)}</h3>
      <p class="meta">Delivered via <a href="{e(item.pr_url)}">pull request #{e(item.pr_number)}</a>.
        Sign-off: <span class="badge {'ok' if not item.needs_signoff else ''}">{e(item.signoff_text)}</span></p>
    </div>""" for item in items)
    return f"""  <div class="section">
    <h2 style="font-size:1.1rem">{e(label)}</h2>
    {cov_line}
{cards}
  </div>"""


def render_awaiting_signoff(items: list, meta: dict) -> str:
    e = B.esc
    if not items:
        return '<p class="empty">Nothing is waiting on your decision right now.</p>'
    cards = []
    for item in items:
        evidence = "".join(f"<li>{e(ev)}</li>" for ev in item.evidence) or "<li>no evidence recorded</li>"
        cards.append(f"""    <div class="card">
      <h3>{e(item.title)}</h3>
      <p class="meta">Delivered via <a href="{e(item.pr_url)}">pull request #{e(item.pr_number)}</a>.
        Current state: <span class="badge">{e(item.signoff_text)}</span></p>
      <p class="meta">Before this can be signed off:</p>
      <ul class="evidence">{evidence}</ul>
    </div>""")
    return "\n".join(cards)


def render_change_requests(items: list) -> str:
    e = B.esc
    if not items:
        return '<p class="empty">No open change requests right now.</p>'
    return "\n".join(
        f'    <div class="card"><h3>{e(item.title)}</h3>'
        f'<p class="meta">Being assessed before it can go ahead.</p></div>'
        for item in items)


def render_in_progress(items: list) -> str:
    e = B.esc
    if not items:
        return '<p class="empty">Nothing is currently in progress.</p>'
    return "\n".join(
        f'    <div class="card"><h3>{e(item.title)}</h3>'
        f'<p class="meta">{e(item.plain_status)}</p></div>'
        for item in items)


def render_html(delivered: list[Delivered], change_requests: list[ChangeRequest],
                 in_progress: list[InProgress], coverage: dict, meta: dict, note: str) -> str:
    e = B.esc
    groups = group_by_requirement(delivered)
    awaiting = [d for d in delivered if d.needs_signoff]

    delivered_html = ("\n".join(
        render_delivered_group(label, items, coverage, meta) for label, items in groups
    )) or '<p class="empty">Nothing has been delivered yet.</p>'

    note_html = f'<p class="meta">{e(note)}</p>' if note else ""

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Delivery portal — {e(meta.get('repo', ''))}</title>
<style>{B.CSS}{EXTRA_CSS}</style>
</head><body><main>
<h1>Delivery portal</h1>
<p class="sub">
  What has actually been delivered, what needs your decision, and what is
  still in progress — computed from merged pull requests, from
  <code>requirements/coverage.yaml</code>'s own checks, and from
  <code>policies/signoff.yaml</code>. Generated {e(meta.get('generated_at', ''))}
  from <a href="{e(meta.get('repo_url',''))}">{e(meta.get('repo',''))}</a>.
</p>
{note_html}

<div class="section">
  <h2 style="font-size:1.25rem">Delivered</h2>
{delivered_html}
</div>

<div class="section">
  <h2 style="font-size:1.25rem">Awaiting your sign-off</h2>
{render_awaiting_signoff(awaiting, meta)}
</div>

<div class="section">
  <h2 style="font-size:1.25rem">Open change requests</h2>
{render_change_requests(change_requests)}
</div>

<div class="section">
  <h2 style="font-size:1.25rem">In progress</h2>
{render_in_progress(in_progress)}
</div>

<footer>
  Generated {e(meta.get('generated_at', ''))} from
  <a href="{e(meta.get('repo_url',''))}">{e(meta.get('repo',''))}</a> ·
  sources: merged pull requests, <code>requirements/coverage.yaml</code>,
  <code>policies/signoff.yaml</code>.
</footer>
</main></body></html>
"""


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "portal" / "site")
    ap.add_argument("--repo", default="Shashank2577/foundry-program")
    ap.add_argument("--ref", default="HEAD", help="git ref to scan for delivered work")
    ap.add_argument("--no-github", action="store_true",
                    help="git only — nothing can be confirmed delivered without gh")
    args = ap.parse_args()

    policy = SC.load_policy(SC.SIGNOFF_POLICY)
    facts = STATUS.collect_facts(not args.no_github)
    coverage = STATUS.evaluate(STATUS.load_coverage(), REPO_ROOT, facts)

    commits = B.collect_commits(args.ref)
    if args.no_github:
        delivered_map: dict = {}
        issues: list = []
        note = "gh unavailable (--no-github): nothing here can be confirmed as delivered."
    else:
        pulls = B.collect_pulls(commits)
        delivered_map = delivered_issue_numbers(commits, pulls)
        issues = collect_issues()
        note = ""

    issues_by_number = {i["number"]: i for i in issues}
    delivered = build_delivered(issues_by_number, delivered_map, coverage, policy,
                                fetch_events_safely)
    change_requests = build_change_requests(issues)
    exclude = set(delivered_map) | {c.issue for c in change_requests}
    in_progress = build_in_progress(issues, exclude)

    repo = args.repo or "Shashank2577/foundry-program"
    meta = {
        "repo": repo,
        "repo_url": f"https://github.com/{repo}",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "portal.html").write_text(
        render_html(delivered, change_requests, in_progress, coverage, meta, note))
    B.write_page(args.out, "portal.html", "Delivery portal",
                "What was delivered, what needs sign-off, what is open — for the client")

    print(f"portal: {len(delivered)} delivered, {sum(1 for d in delivered if d.needs_signoff)} "
          f"awaiting sign-off, {len(change_requests)} open change request(s), "
          f"{len(in_progress)} in progress")
    print(f"wrote {args.out}/portal.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
