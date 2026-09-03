#!/usr/bin/env python3
"""Build the traceability matrix: REQ -> commits -> merged PRs.

Computed, never authored. Every cell comes from `requirements/index.md`,
from commit trailers on the default branch, and from GitHub's own record
of which PR carried which commit. Nothing is hand-maintained, so nothing
can quietly go stale.

    dashboards/build.py --out dashboards/site
    dashboards/build.py --out /tmp/site --no-github   # git only, offline

Writes traceability.html, index.html and traceability.json. The JSON is
the interchange format for anything else that needs this data — the
standup digest reads it rather than recomputing it.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REQ_INDEX = REPO_ROOT / "requirements" / "index.md"

# `| REQ-001 | text… | §1 P1–P2 |`
REQ_ROW = re.compile(r"^\|\s*(REQ-\d{3})\s*\|(.+?)\|(.*?)\|\s*$")
REQ_IN_TRAILER = re.compile(r"REQ-\d{3}")

GREEN, AMBER, RED = "green", "amber", "red"

STATUS_LABEL = {
    GREEN: "traced",
    AMBER: "on main, no PR",
    RED: "untraced",
}
STATUS_BLURB = {
    GREEN: "at least one commit carrying this requirement reached main through a merged pull request",
    AMBER: "commits exist on main but none is attributable to a merged pull request — a direct push, or seed history",
    RED: "no commit on main carries this requirement",
}


@dataclass
class Commit:
    sha: str
    subject: str
    date: str
    trailers: dict[str, str]

    @property
    def requirements(self) -> list[str]:
        return REQ_IN_TRAILER.findall(self.trailers.get("Requirement", ""))

    @property
    def role(self) -> str:
        return self.trailers.get("Agent-Role", "unknown")

    @property
    def harness(self) -> str:
        return self.trailers.get("Harness", "unknown")


@dataclass
class Row:
    req: str
    text: str
    prd: str
    status: str = RED
    commits: list[dict] = field(default_factory=list)
    pulls: list[dict] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Parsing — pure, so it is testable without a repository
# --------------------------------------------------------------------------

def parse_requirements(markdown: str) -> list[tuple[str, str, str]]:
    """Pull (id, text, prd-section) out of the requirement index table."""
    out = []
    for line in markdown.splitlines():
        m = REQ_ROW.match(line.strip())
        if m:
            out.append((m.group(1), m.group(2).strip(), m.group(3).strip()))
    return out


def parse_commits(raw: str) -> list[Commit]:
    """Parse the \\x01-delimited `git log` records emitted by collect_commits."""
    commits = []
    for record in raw.split("\x01"):
        record = record.strip("\n")
        if not record:
            continue
        parts = record.split("\x00")
        if len(parts) < 4:
            continue
        sha, subject, date, trailer_block = parts[0], parts[1], parts[2], parts[3]
        trailers: dict[str, str] = {}
        for line in trailer_block.splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                trailers[key.strip()] = value.strip()
        commits.append(Commit(sha.strip(), subject, date, trailers))
    return commits


def build_matrix(
    requirements: list[tuple[str, str, str]],
    commits: list[Commit],
    pulls_for_sha: dict[str, list[dict]],
) -> list[Row]:
    """Join requirements to commits to PRs. This is the whole computation."""
    rows = [Row(req=r, text=t, prd=p) for r, t, p in requirements]
    by_req = {row.req: row for row in rows}

    # A commit can name a requirement that is not in the index — that is a
    # defect in one of them, and hiding it would defeat the point.
    orphans: dict[str, Row] = {}

    for commit in commits:
        for req in commit.requirements:
            row = by_req.get(req)
            if row is None:
                row = orphans.setdefault(
                    req, Row(req=req, text="⚠ not in requirements/index.md", prd="—")
                )
            row.commits.append(
                {
                    "sha": commit.sha[:7],
                    "full_sha": commit.sha,
                    "subject": commit.subject,
                    "date": commit.date,
                    "role": commit.role,
                    "harness": commit.harness,
                }
            )
            if commit.role not in row.roles:
                row.roles.append(commit.role)
            for pr in pulls_for_sha.get(commit.sha, []):
                if pr["number"] not in [p["number"] for p in row.pulls]:
                    row.pulls.append(pr)

    for row in list(by_req.values()) + list(orphans.values()):
        if row.pulls:
            row.status = GREEN
        elif row.commits:
            row.status = AMBER
        else:
            row.status = RED

    return rows + sorted(orphans.values(), key=lambda r: r.req)


# --------------------------------------------------------------------------
# Collection — talks to git and GitHub
# --------------------------------------------------------------------------

def run(cmd: list[str]) -> str:
    return subprocess.run(cmd, cwd=REPO_ROOT, check=True, capture_output=True,
                          text=True).stdout


def collect_commits(ref: str) -> list[Commit]:
    raw = run(["git", "log", ref,
               "--format=%H%x00%s%x00%aI%x00%(trailers:only,unfold)%x01"])
    return parse_commits(raw)


def collect_pulls(commits: list[Commit]) -> dict[str, list[dict]]:
    """Ask GitHub which merged PR carried each commit.

    Authoritative, and merge-strategy agnostic — squash, rebase and merge
    commits all answer this endpoint correctly, where parsing subjects for
    `(#123)` does not. Failures degrade to 'no PR' (amber) rather than
    aborting the build: a matrix that renders with a caveat beats no matrix.
    """
    out: dict[str, list[dict]] = {}
    for commit in commits:
        if not commit.requirements:
            continue
        try:
            data = json.loads(run([
                "gh", "api",
                f"repos/{{owner}}/{{repo}}/commits/{commit.sha}/pulls",
                "--jq", "[.[] | select(.merged_at != null) | "
                        "{number, url: .html_url, title, merged_at}]",
            ]) or "[]")
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            continue
        if data:
            out[commit.sha] = data
    return out


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

CSS = """
:root {
  --bg:#fff; --fg:#1a1a1a; --muted:#616161; --line:#e3e3e3; --card:#fafafa;
  --green:#1a7f37; --green-bg:#dafbe1; --amber:#9a6700; --amber-bg:#fff8c5;
  --red:#cf222e; --red-bg:#ffebe9; --link:#0969da;
}
@media (prefers-color-scheme: dark) {
  :root { --bg:#0d1117; --fg:#e6edf3; --muted:#9198a1; --line:#30363d;
          --card:#161b22; --green:#3fb950; --green-bg:#12261e; --amber:#d29922;
          --amber-bg:#272115; --red:#f85149; --red-bg:#25171c; --link:#4493f8; }
}
* { box-sizing:border-box }
body { margin:0; padding:2rem 1.25rem 4rem; background:var(--bg); color:var(--fg);
  font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif; }
main { max-width:1100px; margin:0 auto }
h1 { font-size:1.6rem; margin:0 0 .25rem }
.sub { color:var(--muted); margin:0 0 2rem; font-size:.9rem }
.sub code { font-size:.85em }
a { color:var(--link) }
.tiles { display:flex; gap:.75rem; flex-wrap:wrap; margin-bottom:2rem }
.tile { flex:1 1 130px; min-width:0; border:1px solid var(--line); border-radius:8px;
  padding:.85rem 1rem; background:var(--card) }
.tile .n { font-size:1.9rem; font-weight:650; line-height:1.1 }
.tile .l { color:var(--muted); font-size:.78rem; text-transform:uppercase;
  letter-spacing:.04em }
.scroll { overflow-x:auto; border:1px solid var(--line); border-radius:8px }
table { border-collapse:collapse; width:100%; min-width:760px; font-size:.88rem }
th { text-align:left; padding:.6rem .8rem; border-bottom:1px solid var(--line);
  background:var(--card); font-weight:600; white-space:nowrap }
td { padding:.7rem .8rem; border-bottom:1px solid var(--line); vertical-align:top }
tr:last-child td { border-bottom:none }
.req { font-weight:650; white-space:nowrap; font-variant-numeric:tabular-nums }
.pill { display:inline-block; padding:.1rem .5rem; border-radius:99px;
  font-size:.75rem; font-weight:600; white-space:nowrap }
.green { color:var(--green); background:var(--green-bg) }
.amber { color:var(--amber); background:var(--amber-bg) }
.red   { color:var(--red);   background:var(--red-bg) }
.mono { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.82em }
.muted { color:var(--muted) }
.legend { margin-top:1.5rem; font-size:.85rem; color:var(--muted) }
.legend li { margin:.3rem 0 }
ul.bare { list-style:none; padding:0; margin:0 }
ul.bare li { margin:.15rem 0 }
footer { margin-top:2.5rem; padding-top:1rem; border-top:1px solid var(--line);
  color:var(--muted); font-size:.82rem }
"""


def esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def render_html(rows: list[Row], meta: dict) -> str:
    counts = {s: sum(1 for r in rows if r.status == s) for s in (GREEN, AMBER, RED)}
    repo_url = meta.get("repo_url", "")

    body = []
    for row in rows:
        commits = "".join(
            f'<li><a class="mono" href="{repo_url}/commit/{esc(c["full_sha"])}">'
            f'{esc(c["sha"])}</a> {esc(c["subject"][:60])}'
            f'<br><span class="muted mono">{esc(c["role"])} · {esc(c["harness"])}</span></li>'
            for c in row.commits[:6]
        ) or '<span class="muted">—</span>'
        if len(row.commits) > 6:
            commits += f'<li class="muted">+{len(row.commits) - 6} more</li>'

        pulls = "".join(
            f'<li><a href="{esc(p["url"])}">#{esc(p["number"])}</a> '
            f'{esc(p["title"][:50])}</li>' for p in row.pulls
        ) or '<span class="muted">—</span>'

        body.append(f"""      <tr>
        <td class="req">{esc(row.req)}</td>
        <td><span class="pill {row.status}">{esc(STATUS_LABEL[row.status])}</span></td>
        <td>{esc(row.text[:150])}<br><span class="muted mono">{esc(row.prd)}</span></td>
        <td><ul class="bare">{commits}</ul></td>
        <td><ul class="bare">{pulls}</ul></td>
      </tr>""")

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Traceability matrix — {esc(meta.get('repo', ''))}</title>
<style>{CSS}</style>
</head><body><main>
<h1>Traceability matrix</h1>
<p class="sub">
  Every requirement in <code>requirements/index.md</code>, joined to the commits
  that carry its <code>Requirement:</code> trailer on <code>{esc(meta.get('ref', 'main'))}</code>,
  joined to the merged pull requests those commits arrived in.
  Computed, never authored — nothing on this page is hand-maintained.
</p>

<div class="tiles">
  <div class="tile"><div class="n">{len(rows)}</div><div class="l">requirements</div></div>
  <div class="tile"><div class="n" style="color:var(--green)">{counts[GREEN]}</div><div class="l">traced</div></div>
  <div class="tile"><div class="n" style="color:var(--amber)">{counts[AMBER]}</div><div class="l">on main, no PR</div></div>
  <div class="tile"><div class="n" style="color:var(--red)">{counts[RED]}</div><div class="l">untraced</div></div>
  <div class="tile"><div class="n">{meta.get('commits_scanned', 0)}</div><div class="l">commits scanned</div></div>
</div>

<div class="scroll"><table>
  <thead><tr>
    <th>REQ</th><th>Status</th><th>Requirement</th>
    <th>Commits (trailer)</th><th>Merged PRs</th>
  </tr></thead>
  <tbody>
{chr(10).join(body)}
  </tbody>
</table></div>

<ul class="legend">
  <li><span class="pill green">traced</span> {esc(STATUS_BLURB[GREEN])}</li>
  <li><span class="pill amber">on main, no PR</span> {esc(STATUS_BLURB[AMBER])}</li>
  <li><span class="pill red">untraced</span> {esc(STATUS_BLURB[RED])}</li>
</ul>

<footer>
  Generated {esc(meta.get('generated_at', ''))} from
  <a href="{esc(repo_url)}">{esc(meta.get('repo', ''))}</a> at
  <span class="mono">{esc(meta.get('head', '')[:7])}</span>.
  {esc(meta.get('note', ''))}
</footer>
</main></body></html>
"""


INDEX_HTML = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Foundry dashboards</title>
<style>{css}</style>
</head><body><main>
<h1>Foundry dashboards</h1>
<p class="sub">Generated views over the program's own event history. Nothing here
is written by hand; if a page is wrong, the generator is wrong.</p>
<div class="tiles">
{cards}
</div>
<footer>Generated {generated_at} · <a href="{repo_url}">{repo}</a></footer>
</main></body></html>
"""


PAGE_SUFFIX = ".page.json"


def write_page(out: Path, href: str, title: str, description: str) -> None:
    """Declare an index entry for a generated page, next to its HTML.

    Every generator (this one included) calls this right after writing its
    own `<name>.html`. `build.py` discovers pages by globbing these sidecars
    rather than enumerating them, so a new generator never requires an edit
    to this file — and a page cannot land on disk while staying invisible
    to the index, the failure mode this replaces.
    """
    stem = Path(href).stem
    (out / f"{stem}{PAGE_SUFFIX}").write_text(
        json.dumps({"href": href, "title": title, "description": description}, indent=2)
    )


def discover_pages(out: Path) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Glob declared page entries out of `out`, and report the rest.

    Returns `(pages, orphans)`. `pages` is `(href, title, description)`
    sorted by href, so the index order is deterministic regardless of the
    order the filesystem hands back matches. `orphans` is the sorted list
    of `*.html` files on disk with no matching sidecar — a generator that
    forgot to call `write_page()` shows up here instead of silently
    missing from the index.
    """
    pages: list[tuple[str, str, str]] = []
    declared_hrefs: set[str] = set()
    for sidecar in out.glob(f"*{PAGE_SUFFIX}"):
        data = json.loads(sidecar.read_text())
        pages.append((data["href"], data["title"], data["description"]))
        declared_hrefs.add(data["href"])
    pages.sort(key=lambda p: p[0])

    orphans = sorted(
        p.name for p in out.glob("*.html")
        if p.name != "index.html" and p.name not in declared_hrefs
    )
    return pages, orphans


def render_index(pages: list[tuple[str, str, str]], meta: dict) -> str:
    cards = "\n".join(
        f'<div class="tile"><div class="n" style="font-size:1.05rem">'
        f'<a href="{esc(href)}">{esc(title)}</a></div>'
        f'<div class="l" style="text-transform:none;letter-spacing:0">{esc(desc)}</div></div>'
        for href, title, desc in pages
    )
    return INDEX_HTML.format(
        css=CSS, cards=cards,
        generated_at=esc(meta.get("generated_at", "")),
        repo_url=esc(meta.get("repo_url", "")), repo=esc(meta.get("repo", "")),
    )


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "dashboards" / "site")
    ap.add_argument("--ref", default="HEAD", help="git ref to scan")
    ap.add_argument("--repo", default="", help="owner/name, for links")
    ap.add_argument("--no-github", action="store_true",
                    help="skip the PR lookup; everything traced becomes amber")
    args = ap.parse_args()

    if not REQ_INDEX.is_file():
        sys.exit(f"build: {REQ_INDEX.relative_to(REPO_ROOT)} not found")

    requirements = parse_requirements(REQ_INDEX.read_text())
    if not requirements:
        sys.exit("build: requirements/index.md has no REQ rows — refusing to "
                 "publish an empty matrix")

    commits = collect_commits(args.ref)
    note = ""
    if args.no_github:
        pulls, note = {}, "PR lookup skipped (--no-github): no row can be green."
    else:
        pulls = collect_pulls(commits)

    rows = build_matrix(requirements, commits, pulls)
    repo = args.repo or "Shashank2577/foundry-program"
    meta = {
        "repo": repo,
        "repo_url": f"https://github.com/{repo}",
        "ref": args.ref,
        "head": commits[0].sha if commits else "",
        "commits_scanned": len(commits),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "note": note,
    }

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "traceability.html").write_text(render_html(rows, meta))
    (args.out / "traceability.json").write_text(
        json.dumps({"meta": meta, "rows": [asdict(r) for r in rows]}, indent=2)
    )
    write_page(args.out, "traceability.html", "Traceability matrix",
               "REQ → commits → merged PRs, computed from trailers")

    # The index lists whichever pages have declared themselves, so running
    # this generator alone never publishes a link to a page that isn't
    # there. A page on disk that never declared itself is reported, not
    # silently dropped from the index.
    pages, orphans = discover_pages(args.out)
    for orphan in orphans:
        print(f"build: {orphan} is on disk but has no {PAGE_SUFFIX} entry — "
              f"its generator never called write_page(); omitted from the index")
    (args.out / "index.html").write_text(render_index(pages, meta))

    counts = {s: sum(1 for r in rows if r.status == s) for s in (GREEN, AMBER, RED)}
    print(f"traceability: {len(rows)} requirements — "
          f"{counts[GREEN]} traced, {counts[AMBER]} on main without a PR, "
          f"{counts[RED]} untraced ({len(commits)} commits scanned)")
    print(f"wrote {args.out}/traceability.html, traceability.json, index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
