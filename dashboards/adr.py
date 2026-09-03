#!/usr/bin/env python3
"""Build the ADR dashboard: an index and full rendering of adrs/*.md.

The work item that requested this (#105) names the source directory as
`decisions/adr/`. The dependency it names (#103, delivered as PR #111)
actually established `adrs/`, per PRD §14 and
`role-packs/architect/templates/adr.md` — there is no `decisions/adr/` in
this repository. This generator reads the directory that actually exists;
see the PR body for this discrepancy rather than a silent guess.

    dashboards/adr.py --out dashboards/site

Writes adr.html and adr.json. Reads nothing but the filesystem — no `gh`
calls — so unlike qa.py or build.py it needs no network and cannot degrade.

Every file in adrs/ except README.md (the directory's own doc, not a
decision record) is treated as an ADR. A file that fails to parse is
listed with its parse error rather than dropped, because a missing record
is a worse failure than an ugly one.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build as B  # noqa: E402 — shared CSS, escaping, REQ-index parsing

REPO_ROOT = HERE.parent
ADR_DIR = REPO_ROOT / "adrs"
REQ_INDEX = REPO_ROOT / "requirements" / "index.md"

TITLE_RE = re.compile(r"^#\s*ADR-(\d{4}):\s*(.+?)\s*$", re.MULTILINE)
# A field's value may soft-wrap onto following lines (real ADR prose does
# this); a continuation line is anything that isn't blank and doesn't open
# a new field or heading of its own.
FIELD_RE = re.compile(
    r"^\*\*([^*:]+):\*\*[ \t]*(.+(?:\n(?!\s*$|\s*\*\*[^*:]+:\*\*|#).+)*)",
    re.MULTILINE)
SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
SUPERSEDED_RE = re.compile(r"superseded by ADR-(\d{4})", re.IGNORECASE)
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
# Bold in ADR bodies is exclusively a leading "**Label:**" on a bullet or
# paragraph (see role-packs/architect/templates/adr.md). Matching `**…**`
# anywhere would also pair unrelated literal `**` globs that show up inside
# backtick code spans (`.github/workflows/**`, `policies/**`), bolding
# everything between two glob patterns paragraphs apart.
LEADING_BOLD_RE = re.compile(r"^\*\*([^*]+?):\*\*")

STATUS_ORDER = ["accepted", "proposed", "superseded"]
STATUS_PILL = {"accepted": "green", "proposed": "amber", "superseded": "red"}


@dataclass
class Adr:
    id: str
    filename: str
    title: str = ""
    status_raw: str = ""
    status: str = ""                       # accepted | proposed | superseded
    superseded_by: str | None = None       # ADR id this record is superseded by
    supersedes: list[str] = field(default_factory=list)  # filled by link_supersession
    work_item: str = ""
    requirements: list[str] = field(default_factory=list)
    unknown_requirements: list[str] = field(default_factory=list)
    decided_by: str = ""
    date: str = ""
    sections: list[tuple[str, str]] = field(default_factory=list)
    error: str | None = None


# --------------------------------------------------------------------------
# Parsing — pure, so it is testable without a directory on disk
# --------------------------------------------------------------------------

def parse_sections(text: str) -> list[tuple[str, str]]:
    """Split on `## Heading` lines, in document order."""
    matches = list(SECTION_RE.finditer(text))
    out = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out.append((m.group(1).strip(), text[start:end].strip()))
    return out


def parse_adr(filename: str, text: str, known_reqs: set[str]) -> Adr:
    fallback_id = filename.split("-", 1)[0]

    title_m = TITLE_RE.search(text)
    if title_m is None:
        return Adr(id=fallback_id, filename=filename,
                    error="no `# ADR-NNNN: Title` heading found")

    adr_id, title = title_m.group(1), title_m.group(2)
    fields = {k.strip(): re.sub(r"\s+", " ", v).strip()
              for k, v in FIELD_RE.findall(text)}

    status_raw = fields.get("Status", "")
    if not status_raw:
        return Adr(id=adr_id, filename=filename, title=title,
                    error="missing **Status:** field")

    superseded_m = SUPERSEDED_RE.search(status_raw)
    status = "superseded" if superseded_m else status_raw.lower().strip()
    superseded_by = superseded_m.group(1) if superseded_m else None

    reqs = sorted(set(re.findall(r"REQ-\d{3}", fields.get("Requirement", ""))))
    unknown = [r for r in reqs if r not in known_reqs]

    return Adr(
        id=adr_id, filename=filename, title=title,
        status_raw=status_raw, status=status, superseded_by=superseded_by,
        work_item=fields.get("Work item", ""),
        requirements=reqs, unknown_requirements=unknown,
        decided_by=fields.get("Decided by", ""), date=fields.get("Date", ""),
        sections=parse_sections(text),
    )


def link_supersession(records: list[Adr]) -> None:
    """Fill `supersedes` from every other record's `superseded_by`, so a
    superseding record links back even though only the superseded record's
    own file states the relationship."""
    by_id = {r.id: r for r in records}
    for r in records:
        if r.superseded_by and r.superseded_by in by_id:
            by_id[r.superseded_by].supersedes.append(r.id)
    for r in records:
        r.supersedes.sort()


def scan_adrs(adr_dir: Path, known_reqs: set[str]) -> list[Adr]:
    if not adr_dir.is_dir():
        return []
    records = [
        parse_adr(path.name, path.read_text(), known_reqs)
        for path in sorted(adr_dir.iterdir())
        if path.suffix == ".md" and path.name != "README.md"
    ]
    records.sort(key=lambda r: r.id)
    link_supersession(records)
    return records


def collect_known_reqs() -> set[str]:
    if not REQ_INDEX.is_file():
        print(f"adr: {REQ_INDEX.relative_to(REPO_ROOT)} not found; every REQ "
              "citation will read as unknown", file=sys.stderr)
        return set()
    return {req for req, _, _ in B.parse_requirements(REQ_INDEX.read_text())}


def date_sort_key(adr: Adr) -> tuple:
    """Records with a real date sort first, oldest first; unparseable or
    absent dates sort last, by id, rather than crashing the sort."""
    m = DATE_RE.search(adr.date)
    return (0, m.group(1)) if m else (1, adr.id)


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

WORK_ITEM_RE = re.compile(r"^([\w.-]+/[\w.-]+)#(\d+)")


def work_item_url(work_item: str) -> str | None:
    m = WORK_ITEM_RE.match(work_item.strip())
    return f"https://github.com/{m.group(1)}/issues/{m.group(2)}" if m else None


def inline(escaped: str) -> str:
    return LEADING_BOLD_RE.sub(r"<strong>\1:</strong>", escaped, count=1)


def render_body(text: str) -> str:
    """Blank-line-delimited blocks, each a heading, a bullet list, or a
    paragraph — the only shapes role-packs/architect/templates/adr.md uses.
    A bullet's or paragraph's soft-wrapped continuation lines (no leading
    `- `) are folded back into the item they wrap, matching how the field
    values above are folded."""
    e = B.esc
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        if lines[0].startswith("### "):
            out.append(f"<h5>{inline(e(lines[0][4:]))}</h5>")
            lines = lines[1:]
            if not lines:
                continue
        if lines[0].startswith("- "):
            items: list[str] = []
            for line in lines:
                if line.startswith("- "):
                    items.append(line[2:])
                else:
                    items[-1] = f"{items[-1]} {line}"
            out.append("<ul>" + "".join(f"<li>{inline(e(i))}</li>" for i in items) + "</ul>")
        else:
            out.append(f"<p>{inline(e(' '.join(lines)))}</p>")
    return "\n".join(out)


def req_links(reqs: list[str], unknown: list[str], repo_url: str) -> str:
    e = B.esc
    items = []
    for r in reqs:
        if r in unknown:
            items.append(f'<span class="mono" title="not in requirements/index.md">'
                         f'{e(r)} ⚠</span>')
        else:
            items.append(f'<a href="traceability.html#{e(r)}">{e(r)}</a>')
    return ", ".join(items) or '<span class="muted">—</span>'


def status_pill(adr: Adr) -> str:
    e = B.esc
    cls = STATUS_PILL.get(adr.status, "amber")
    label = adr.status or "unknown"
    return f'<span class="pill {cls}">{e(label)}</span>'


def index_row(adr: Adr, repo_url: str) -> str:
    e = B.esc
    if adr.error:
        return (f'<tr><td class="req">{e(adr.filename)}</td>'
                f'<td colspan="5"><span class="pill red">parse error</span> {e(adr.error)}</td></tr>')

    superseded_note = ""
    if adr.superseded_by:
        superseded_note = (f' <a href="#adr-{e(adr.superseded_by)}">→ ADR-{e(adr.superseded_by)}</a>')
    if adr.supersedes:
        links = ", ".join(f'<a href="#adr-{e(s)}">ADR-{e(s)}</a>' for s in adr.supersedes)
        superseded_note += f' <span class="muted">(supersedes {links})</span>'

    wi_url = work_item_url(adr.work_item)
    wi_html = (f'<a href="{e(wi_url)}">{e(adr.work_item)}</a>' if wi_url
               else e(adr.work_item) or '<span class="muted">—</span>')

    return f"""      <tr>
        <td class="req"><a href="#adr-{e(adr.id)}">ADR-{e(adr.id)}</a></td>
        <td>{e(adr.title)}</td>
        <td>{status_pill(adr)}{superseded_note}</td>
        <td class="mono">{e(adr.date) or '<span class="muted">—</span>'}</td>
        <td>{e(adr.decided_by) or '<span class="muted">—</span>'}</td>
        <td>{wi_html}</td>
        <td>{req_links(adr.requirements, adr.unknown_requirements, repo_url)}</td>
      </tr>"""


INDEX_COLS = ("<th>ID</th><th>Title</th><th>Status</th><th>Date</th>"
              "<th>Decided by</th><th>Work item</th><th>Requirements</th>")


def render_full_record(adr: Adr, repo_url: str) -> str:
    e = B.esc
    if adr.error:
        return (f'<section id="adr-{e(adr.id)}">'
                f'<h3>{e(adr.filename)}</h3>'
                f'<p><span class="pill red">parse error</span> {e(adr.error)}</p>'
                f'</section>')

    superseded_note = ""
    if adr.superseded_by:
        superseded_note = (f'<p><span class="pill red">superseded</span> by '
                           f'<a href="#adr-{e(adr.superseded_by)}">ADR-{e(adr.superseded_by)}</a></p>')
    if adr.supersedes:
        links = ", ".join(f'<a href="#adr-{e(s)}">ADR-{e(s)}</a>' for s in adr.supersedes)
        superseded_note += f'<p class="muted">Supersedes {links}.</p>'

    wi_url = work_item_url(adr.work_item)
    wi_html = (f'<a href="{e(wi_url)}">{e(adr.work_item)}</a>' if wi_url
               else e(adr.work_item) or '<span class="muted">—</span>')

    sections = "\n".join(
        f'<h4>{e(name)}</h4>\n{render_body(body)}' for name, body in adr.sections
    )

    return f"""    <section id="adr-{e(adr.id)}">
      <h3>ADR-{e(adr.id)}: {e(adr.title)}</h3>
      <p>{status_pill(adr)}
        · date <span class="mono">{e(adr.date) or '—'}</span>
        · decided by {e(adr.decided_by) or '—'}
        · work item {wi_html}
        · requirements {req_links(adr.requirements, adr.unknown_requirements, repo_url)}
      </p>
      {superseded_note}
      {sections}
    </section>"""


def render_html(records: list[Adr], meta: dict) -> str:
    e = B.esc
    repo_url = meta.get("repo_url", "")

    ok = [r for r in records if not r.error]
    errors = [r for r in records if r.error]
    counts = {s: sum(1 for r in ok if r.status == s) for s in STATUS_ORDER}

    chrono_rows = "\n".join(index_row(r, repo_url) for r in sorted(ok, key=date_sort_key))
    error_rows = "\n".join(index_row(r, repo_url) for r in errors)

    status_sections = []
    for status in STATUS_ORDER:
        group = [r for r in ok if r.status == status]
        if not group:
            continue
        rows = "\n".join(index_row(r, repo_url) for r in group)
        status_sections.append(f"""<h3 class="status-h">{e(status.title())} ({len(group)})</h3>
<div class="scroll"><table><thead><tr>{INDEX_COLS}</tr></thead><tbody>
{rows}
</tbody></table></div>""")

    records_html = "\n".join(render_full_record(r, repo_url) for r in records) or (
        '<p class="muted">No ADR records found.</p>')

    empty_note = ('<tr><td colspan="7" class="muted">No ADR records found in '
                 '<code>adrs/</code>.</td></tr>')

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Architecture decisions — {e(meta.get('repo', ''))}</title>
<style>{B.CSS}
.status-h{{font-size:.95rem;margin:1.5rem 0 .5rem}}
section{{border:1px solid var(--line);border-radius:8px;padding:1rem 1.25rem;margin:1.25rem 0}}
section h3{{margin-top:0}}
section h4{{font-size:.85rem;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);
  margin:1.1rem 0 .4rem}}
section h5{{font-size:.9rem;margin:.9rem 0 .2rem}}
section p{{margin:.4rem 0}}
section ul{{margin:.3rem 0;padding-left:1.4rem}}
</style>
</head><body><main>
<h1>Architecture decisions</h1>
<p class="sub">
  Every record in <code>adrs/</code> (PRD §14), computed — not hand-curated.
  A record that fails to parse is listed with its parse error rather than
  dropped. Requirement citations link to the
  <a href="traceability.html">traceability matrix</a>; a citation naming a
  requirement not in <code>requirements/index.md</code> is marked ⚠ rather
  than silently linked.
</p>

<div class="tiles">
  <div class="tile"><div class="n">{len(ok)}</div><div class="l">records</div></div>
  <div class="tile"><div class="n" style="color:var(--green)">{counts['accepted']}</div><div class="l">accepted</div></div>
  <div class="tile"><div class="n" style="color:var(--amber)">{counts['proposed']}</div><div class="l">proposed</div></div>
  <div class="tile"><div class="n" style="color:var(--red)">{counts['superseded']}</div><div class="l">superseded</div></div>
  <div class="tile"><div class="n" style="color:var(--red)">{len(errors)}</div><div class="l">parse errors</div></div>
</div>

<h2>By status</h2>
{"".join(status_sections) or '<p class="muted">No parsed records.</p>'}

<h2>Chronological</h2>
<div class="scroll"><table><thead><tr>{INDEX_COLS}</tr></thead><tbody>
{chrono_rows or empty_note}
</tbody></table></div>

{f'<h2>Parse errors</h2><div class="scroll"><table><thead><tr><th>File</th><th colspan="6">Error</th></tr></thead><tbody>{error_rows}</tbody></table></div>' if errors else ""}

<h2>Records</h2>
{records_html}

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
    ap.add_argument("--adr-dir", type=Path, default=ADR_DIR)
    ap.add_argument("--now", default="", help="ISO timestamp; for reproducible runs")
    args = ap.parse_args()

    now = (datetime.fromisoformat(args.now.replace("Z", "+00:00"))
           if args.now else datetime.now(timezone.utc))

    known_reqs = collect_known_reqs()
    records = scan_adrs(args.adr_dir, known_reqs)
    meta = {
        "repo": args.repo,
        "repo_url": f"https://github.com/{args.repo}",
        "generated_at": now.strftime("%Y-%m-%d %H:%M UTC"),
    }

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "adr.html").write_text(render_html(records, meta))
    (args.out / "adr.json").write_text(
        json.dumps({"meta": meta, "records": [asdict(r) for r in records]}, indent=2))
    # Declare this page so build.py's index picks it up. Added when the
    # index moved from a hardcoded list in build.py to generators
    # declaring themselves (#127) — this generator landed in between, so it
    # was the one orphan: on disk, absent from the index.
    B.write_page(args.out, "adr.html", "Architecture decisions",
                 "Decisions taken, why, and what they superseded")

    errors = sum(1 for r in records if r.error)
    print(f"adr: {len(records)} record(s) — {errors} parse error(s)")
    print(f"wrote {args.out}/adr.html, adr.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
