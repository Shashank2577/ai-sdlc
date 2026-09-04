#!/usr/bin/env python3
"""Programme status: what is actually built, computed from the repository.

The traceability matrix answers "did work carrying this REQ trailer reach
main". This answers the harder question — "is the requirement satisfied" —
from the machine-checkable criteria in `requirements/coverage.yaml`.

The two disagree, on purpose. A requirement can be fully traced and barely
satisfied: REQ-004 (Jira swappable) is traced by a commit that mentions
Jira, while no adapter exists. Showing only the trace flatters the
programme, which is exactly how a status page starts lying to a client.

    dashboards/status.py --out dashboards/site
    dashboards/status.py --out /tmp/site --no-github    # skip run history
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build as B  # noqa: E402  — shared CSS and escaping

REPO_ROOT = HERE.parent
COVERAGE = REPO_ROOT / "requirements" / "coverage.yaml"

# §5 names five ceremonies; §14 names the layout. The role list (§3) is not
# here — it lives in requirements/coverage.yaml's `policy.roles.expected`,
# reconciled against role-packs/*/ by `collect_facts`, because a literal
# here is exactly what went stale last time (#185).
PRD_CEREMONIES = ["refinement", "planning", "standup", "review", "retro"]
PRD_DIRS = ["prds", "requirements", "adrs", "role-packs", "ceremonies", "policies",
            "adapters", "dashboards", "portal", "compiler", ".github/workflows"]

PHASES = [
    ("Phase 0", "Prove the spine",
     ["REQ-001", "REQ-002", "REQ-003", "REQ-005", "REQ-009", "REQ-012", "REQ-014"]),
    ("Phase 1", "The team — all roles, ceremonies, estimation",
     ["REQ-006", "REQ-007", "REQ-011"]),
    ("Phase 2", "The client — PRDs, sign-offs, demos, portal",
     ["REQ-008"]),
    ("Phase 3", "Pluggability and learning — Jira, 2nd harness, memory",
     ["REQ-004", "REQ-013"]),
]


def load_yaml() -> dict:
    try:
        import yaml
    except ImportError:  # pragma: no cover
        sys.exit("status: PyYAML is required")
    return yaml.safe_load(COVERAGE.read_text()) or {}


def load_coverage() -> dict:
    return load_yaml().get("requirements", {})


def load_expected_roles() -> list[str]:
    """The reviewable, non-Python-literal source `roles_built` counts against."""
    return list((load_yaml().get("policy") or {}).get("roles", {}).get("expected", []))


def load_self_hosting_policy() -> dict:
    """Defaults match the floor the `delivered_by_agent` check has always used."""
    policy = (load_yaml().get("policy") or {}).get("self_hosting") or {}
    return {
        "machinery_at_least": policy.get("machinery_at_least", 1),
        "practice_at_least": policy.get("practice_at_least", 10),
    }


# A note asserting the requirement is unbuilt, phrased in any of these ways,
# contradicts itself the moment the requirement's own checks score above
# zero. Eight of fourteen notes drifted into exactly this state (#159) —
# accurate when written, never revisited once the score moved. Deliberately
# crude pattern matching: it has almost no false-positive surface, and it
# catches the one failure that has actually happened, repeatedly.
CONTRADICTION_PATTERNS = [re.compile(p, re.I) for p in (
    r"nothing built", r"does not exist", r"no\b[\w /.'-]*\bexists?\b", r"unproven",
)]


def note_contradicts_checks(notes: str, pct: int) -> str | None:
    """The matched phrase if `notes` denies work that `pct` says exists, else None."""
    if pct <= 0 or not notes:
        return None
    for pat in CONTRADICTION_PATTERNS:
        m = pat.search(notes)
        if m:
            return m.group(0)
    return None


def self_hosting_verdict(facts: dict, policy: dict) -> dict:
    """What the delivered-PR count actually supports claiming, and at what threshold."""
    delivered = facts.get("agent_delivered_prs", 0)
    merged = facts.get("merged_prs", 0)
    machinery_at_least = policy["machinery_at_least"]
    practice_at_least = policy["practice_at_least"]
    machinery_proven = delivered >= machinery_at_least
    practice_proven = delivered >= practice_at_least
    return {
        "delivered": delivered,
        "merged": merged,
        "machinery_at_least": machinery_at_least,
        "practice_at_least": practice_at_least,
        "machinery_proven": machinery_proven,
        "practice_proven": practice_proven,
    }


# --------------------------------------------------------------------------
# Check evaluation — pure apart from the filesystem it is asked about
# --------------------------------------------------------------------------

def run_check(check: dict, root: Path, facts: dict) -> tuple[bool, str]:
    """(passed, description). Unknown check kinds fail loudly rather than pass."""
    if "exists" in check:
        target = check["exists"]
        return (root / target).exists(), f"`{target}` exists"
    if "glob" in check:
        pattern = check["glob"]
        return any(root.glob(pattern)), f"`{pattern}` matches something"
    if "count" in check:
        spec = check["count"]
        n = len(list(root.glob(spec["glob"])))
        return n >= spec["at_least"], f"`{spec['glob']}` >= {spec['at_least']} (found {n})"
    if "grep" in check:
        spec = check["grep"]
        needle = spec["pattern"]
        for path in root.glob(spec["glob"]):
            try:
                if needle in path.read_text():
                    return True, f"`{needle}` found in `{spec['glob']}`"
            except (OSError, UnicodeDecodeError):
                continue
        return False, f"`{needle}` found in `{spec['glob']}`"
    if "delivered_by_agent" in check:
        want = check["delivered_by_agent"]
        got = facts.get("agent_delivered_prs", 0)
        return got >= want, f"{want} PR(s) delivered by a dispatched session (found {got})"
    return False, f"unknown check kind: {sorted(check)}"


def evaluate(coverage: dict, root: Path, facts: dict) -> dict:
    out = {}
    for req, spec in coverage.items():
        results = [run_check(c, root, facts) for c in spec.get("checks", [])]
        passed = sum(1 for ok, _ in results if ok)
        notes = spec.get("notes", "")
        pct = round(100 * passed / len(results)) if results else 0
        out[req] = {
            "summary": spec.get("summary", ""),
            "notes": notes,
            "passed": passed,
            "total": len(results),
            "pct": pct,
            "checks": [{"ok": ok, "text": text} for ok, text in results],
            "contradiction": note_contradicts_checks(notes, pct),
        }
    return out


# --------------------------------------------------------------------------
# Facts about the repository
# --------------------------------------------------------------------------

def gh_json(args: list[str], default):
    try:
        out = subprocess.run(["gh", *args], cwd=REPO_ROOT, check=True,
                             capture_output=True, text=True).stdout
        return json.loads(out) if out.strip() else default
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return default


def collect_facts(use_github: bool, expected_roles: list[str]) -> dict:
    root = REPO_ROOT
    packs_on_disk = sorted(p.name for p in (root / "role-packs").iterdir()
                           if p.is_dir() and (p / "pack.yaml").is_file()) \
        if (root / "role-packs").is_dir() else []
    facts = {
        "roles_expected": expected_roles,
        "roles_built": [r for r in expected_roles if r in packs_on_disk],
        # A pack that exists but has no entry in the expected list — the
        # other direction of the mismatch, invisible before #185.
        "roles_unexpected": [r for r in packs_on_disk if r not in expected_roles],
        "ceremonies_built": [c for c in PRD_CEREMONIES
                             if (root / ".github" / "workflows" / f"{c}.yml").is_file()],
        "dirs_present": [d for d in PRD_DIRS if (root / d).is_dir()],
        "agent_delivered_prs": 0,
        "dispatch_runs": {},
        "merged_prs": 0,
    }
    if not use_github:
        return facts

    runs = gh_json(["run", "list", "--workflow", "dispatch.yml", "--limit", "100",
                    "--json", "conclusion,databaseId"], [])
    for r in runs:
        c = r.get("conclusion") or "in_progress"
        facts["dispatch_runs"][c] = facts["dispatch_runs"].get(c, 0) + 1

    prs = gh_json(["pr", "list", "--state", "merged", "--limit", "200",
                   "--json", "number,headRefName"], [])
    facts["merged_prs"] = len(prs)

    # Self-hosting, measured rather than asserted: a merged PR on a branch for
    # an issue that a dispatch run actually worked. Without that link, "the
    # system builds itself" is a claim, not a number.
    dispatched = set()
    for r in runs:
        jobs = gh_json(["api", f"repos/{{owner}}/{{repo}}/actions/runs/{r['databaseId']}/jobs",
                        "--jq", "[.jobs[].name]"], [])
        for name in jobs:
            m = re.match(r"#(\d+) as ", str(name))
            if m:
                dispatched.add(int(m.group(1)))
    delivered = 0
    for pr in prs:
        m = re.match(r"^(?:story|bug)/FDY-(\d+)-", pr.get("headRefName", ""))
        if m and int(m.group(1)) in dispatched:
            delivered += 1
    facts["agent_delivered_prs"] = delivered
    facts["dispatched_issues"] = sorted(dispatched)
    return facts


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def bar(pct: int) -> str:
    colour = "var(--green)" if pct >= 80 else ("var(--amber)" if pct >= 34 else "var(--red)")
    return (f'<div style="background:var(--line);border-radius:99px;height:7px;'
            f'min-width:70px"><div style="width:{pct}%;background:{colour};'
            f'height:7px;border-radius:99px"></div></div>')


def render(cov: dict, trace: dict, facts: dict, meta: dict, policy: dict) -> str:
    e = B.esc
    trace_status = {r["req"]: r["status"] for r in (trace or {}).get("rows", [])}
    label = {"green": "traced", "amber": "on main, no PR", "red": "untraced"}

    contradictions = {req: c["contradiction"] for req, c in cov.items() if c["contradiction"]}

    rows = []
    for req in sorted(cov):
        c = cov[req]
        t = trace_status.get(req, "red")
        gap = ""
        if c["notes"]:
            gap = f'<br><span class="muted">{e(c["notes"])}</span>'
        if c["contradiction"]:
            gap += (f'<br><span class="pill red">note contradicts its checks</span> '
                    f'<span class="muted">matched "{e(c["contradiction"])}" '
                    f'while scoring {c["pct"]}%</span>')
        rows.append(f"""      <tr>
        <td class="req">{e(req)}</td>
        <td><span class="pill {t}">{e(label.get(t, t))}</span></td>
        <td style="min-width:110px">{bar(c['pct'])}
            <span class="mono muted">{c['passed']}/{c['total']} · {c['pct']}%</span></td>
        <td>{e(c['summary'])}{gap}</td>
      </tr>""")

    phase_rows = []
    for name, desc, reqs in PHASES:
        pcts = [cov[r]["pct"] for r in reqs if r in cov]
        pct = round(sum(pcts) / len(pcts)) if pcts else 0
        phase_rows.append(f"""      <tr>
        <td class="req">{e(name)}</td>
        <td>{e(desc)}</td>
        <td style="min-width:110px">{bar(pct)}
            <span class="mono muted">{pct}%</span></td>
        <td class="mono muted">{e(', '.join(reqs))}</td>
      </tr>""")

    def checklist(items, built, kind, unexpected=None):
        lis = "".join(
            f'<li>{"✓" if i in built else "○"} <span class="mono">{e(i)}</span>'
            f'{"" if i in built else f" <span class=muted>— not built</span>"}</li>'
            for i in items)
        lis += "".join(
            f'<li>⚠ <span class="mono">{e(i)}</span> '
            f'<span class=muted>— pack exists, not in the expected list</span></li>'
            for i in (unexpected or []))
        return lis or f"<li class='muted'>no {kind}</li>"

    overall = round(sum(c["pct"] for c in cov.values()) / len(cov)) if cov else 0
    verdict = self_hosting_verdict(facts, policy)
    delivered = verdict["delivered"]
    runs = facts.get("dispatch_runs", {})
    run_line = ", ".join(f"{n} {k}" for k, n in sorted(runs.items())) or "none yet"

    if not verdict["machinery_proven"]:
        banner_colour = "var(--red)"
        verdict_line = (f'<strong>Self-hosting is unproven.</strong> The machinery '
                        f'threshold is {verdict["machinery_at_least"]} merged pull '
                        f'request delivered by a dispatched agent session; '
                        f'{delivered} have been.')
    elif not verdict["practice_proven"]:
        banner_colour = "var(--amber)"
        verdict_line = (f'<strong>Self-hosting machinery is proven; the practice is '
                        f'not yet.</strong> {delivered} merged pull request(s) have '
                        f'been produced by a dispatched agent session, out of '
                        f'{verdict["merged"]} merged overall — past the machinery '
                        f'threshold of {verdict["machinery_at_least"]}, short of the '
                        f'practice threshold of {verdict["practice_at_least"]} set in '
                        f'<code>requirements/coverage.yaml</code>.')
    else:
        banner_colour = "var(--green)"
        verdict_line = (f'<strong>Self-hosting is proven, as machinery and as '
                        f'practice.</strong> {delivered} merged pull request(s) have '
                        f'been produced by a dispatched agent session, out of '
                        f'{verdict["merged"]} merged overall — past the practice '
                        f'threshold of {verdict["practice_at_least"]} set in '
                        f'<code>requirements/coverage.yaml</code>.')

    contradiction_banner = ""
    if contradictions:
        items = "".join(
            f'<li><span class="mono">{e(req)}</span> — matched "{e(phrase)}"</li>'
            for req, phrase in sorted(contradictions.items()))
        contradiction_banner = f"""
<div class="banner" style="border-left-color:var(--red)">
  <strong>{len(contradictions)} requirement note(s) contradict their own checks.</strong>
  A note denying work the checks say exists is stale prose beside a computed
  number — see requirements/coverage.yaml.
  <ul class="bare">{items}</ul>
</div>"""

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Programme status — {e(meta.get('repo',''))}</title>
<style>{B.CSS}
.pill.green{{color:var(--green);background:var(--green-bg)}}
.banner{{border:1px solid var(--line);border-left:3px solid var(--red);
  background:var(--card);padding:.9rem 1.1rem;border-radius:8px;margin:0 0 2rem}}
</style></head><body><main>
<h1>Programme status</h1>
<p class="sub">
  Computed from the repository. <strong>Traced</strong> means a commit carrying
  the requirement's trailer reached <code>main</code> through a merged PR.
  <strong>Satisfied</strong> is the fraction of that requirement's criteria in
  <code>requirements/coverage.yaml</code> that actually pass. They disagree
  often, and the gap is the point — a requirement can be fully traced and
  barely built.
</p>

<div class="banner" style="border-left-color:{banner_colour}">
  {verdict_line}
  Dispatch runs so far: {e(run_line)}.
</div>
{contradiction_banner}
<div class="tiles">
  <div class="tile"><div class="n">{overall}%</div><div class="l">requirements satisfied</div></div>
  <div class="tile"><div class="n">{len(facts['roles_built'])}/{len(facts['roles_expected'])}</div><div class="l">role packs</div></div>
  <div class="tile"><div class="n">{len(facts['ceremonies_built'])}/{len(PRD_CEREMONIES)}</div><div class="l">ceremonies</div></div>
  <div class="tile"><div class="n">{len(facts['dirs_present'])}/{len(PRD_DIRS)}</div><div class="l">PRD §14 areas</div></div>
  <div class="tile"><div class="n" style="color:{'var(--green)' if delivered else 'var(--red)'}">{delivered}</div><div class="l">agent-delivered PRs</div></div>
</div>

<h2 style="font-size:1.05rem;margin:0 0 .6rem">Rollout (PRD §15)</h2>
<div class="scroll"><table>
  <thead><tr><th>Phase</th><th>Scope</th><th>Satisfied</th><th>Requirements</th></tr></thead>
  <tbody>
{chr(10).join(phase_rows)}
  </tbody>
</table></div>

<h2 style="font-size:1.05rem;margin:2rem 0 .6rem">Requirements — traced vs satisfied</h2>
<div class="scroll"><table>
  <thead><tr><th>REQ</th><th>Traced</th><th>Satisfied</th><th>Requirement</th></tr></thead>
  <tbody>
{chr(10).join(rows)}
  </tbody>
</table></div>

<h2 style="font-size:1.05rem;margin:2rem 0 .6rem">Roles (PRD §3)</h2>
<ul class="bare">{checklist(facts['roles_expected'], facts['roles_built'], 'roles', facts.get('roles_unexpected'))}</ul>

<h2 style="font-size:1.05rem;margin:2rem 0 .6rem">Ceremonies (PRD §5)</h2>
<ul class="bare">{checklist(PRD_CEREMONIES, facts['ceremonies_built'], 'ceremonies')}</ul>

<h2 style="font-size:1.05rem;margin:2rem 0 .6rem">Programme areas (PRD §14)</h2>
<ul class="bare">{checklist(PRD_DIRS, facts['dirs_present'], 'areas')}</ul>

<footer>
  Generated {e(meta.get('generated_at',''))} ·
  criteria in <span class="mono">requirements/coverage.yaml</span>, reviewed like code ·
  <a href="traceability.html">traceability</a> · <a href="standup.html">standup</a>
</footer>
</main></body></html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "dashboards" / "site")
    ap.add_argument("--repo", default="Shashank2577/foundry-program")
    ap.add_argument("--no-github", action="store_true")
    args = ap.parse_args()

    facts = collect_facts(not args.no_github, load_expected_roles())
    cov = evaluate(load_coverage(), REPO_ROOT, facts)
    policy = load_self_hosting_policy()

    trace_path = args.out / "traceability.json"
    trace = json.loads(trace_path.read_text()) if trace_path.is_file() else None
    if trace is None:
        print("status: traceability.json not found — the Traced column will read "
              "`untraced` rather than inventing a status", file=sys.stderr)

    from datetime import datetime, timezone
    meta = {"repo": args.repo,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "status.html").write_text(render(cov, trace, facts, meta, policy))
    (args.out / "status.json").write_text(
        json.dumps({"meta": meta, "facts": facts, "coverage": cov}, indent=2))
    B.write_page(args.out, "status.html", "Programme status",
                 "Traced vs actually satisfied, per requirement and phase")

    if facts["roles_unexpected"]:
        print(f"status: role pack(s) with no entry in policy.roles.expected: "
              f"{', '.join(facts['roles_unexpected'])}", file=sys.stderr)

    overall = round(sum(c["pct"] for c in cov.values()) / len(cov)) if cov else 0
    print(f"status: {overall}% of requirements satisfied, "
          f"{len(facts['roles_built'])}/{len(facts['roles_expected'])} roles, "
          f"{len(facts['ceremonies_built'])}/{len(PRD_CEREMONIES)} ceremonies, "
          f"{facts['agent_delivered_prs']} agent-delivered PR(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
