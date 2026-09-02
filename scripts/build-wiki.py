#!/usr/bin/env python3
"""Generate the wiki from the repository.

A wiki that is typed into a web form drifts from the code within a
sprint, and then quietly lies to whoever reads it next. So every page
here is generated: prose lives in `wiki/`, under review like any other
file, and the factual pages are computed from role packs, the
requirement index and the traceability data.

    build-wiki.py --out build/wiki
    build-wiki.py --out build/wiki --traceability dashboards/site/traceability.json

Nothing in the published wiki is hand-edited. An edit made in the web UI
is overwritten by the next push to main, on purpose.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WIKI_SRC = REPO_ROOT / "wiki"
PACKS = REPO_ROOT / "role-packs"
REQ_INDEX = REPO_ROOT / "requirements" / "index.md"
REQ_ROW = re.compile(r"^\|\s*(REQ-\d{3})\s*\|(.+?)\|(.*?)\|\s*$")

BANNER = (
    "> _Generated from the repository — do not edit this page in the web UI._\n"
    "> _Edits here are overwritten by the next push to `main`. "
    "Change the source instead: {source}_\n"
)


def read_yaml(path: Path) -> dict:
    try:
        import yaml
    except ImportError:  # pragma: no cover
        sys.exit("build-wiki: PyYAML is required")
    return yaml.safe_load(path.read_text()) or {}


def first_paragraph(markdown: str, heading: str) -> str:
    """The prose under a `## <heading>` section, up to the next heading."""
    out, capture = [], False
    for line in markdown.splitlines():
        if line.startswith("## "):
            if capture:
                break
            capture = heading.lower() in line.lower()
            continue
        if capture and line.strip():
            out.append(line.strip())
        elif capture and out:
            break
    return " ".join(out)


def roles_page() -> str:
    rows, detail = [], []
    for manifest in sorted(PACKS.glob("*/pack.yaml")):
        role = manifest.parent.name
        pack = read_yaml(manifest)
        policy = read_yaml(manifest.parent / "policy.yaml")
        budgets = policy.get("budgets", {})
        charter = (manifest.parent / "charter.md").read_text()
        skills = sorted(p.stem for p in (manifest.parent / "skills").glob("*.md"))
        ident = pack.get("identity", {})

        rows.append(
            f"| **{pack.get('name', role)}** | `{role}` | "
            f"{budgets.get('turns', '?')} turns · {budgets.get('tokens', 0):,} tokens · "
            f"{budgets.get('wall_clock_minutes', '?')} min · "
            f"{budgets.get('max_retries', '?')} retries | "
            f"{'yes' if ident.get('provisioned') else '**not provisioned**'} |"
        )
        detail += [
            f"## {pack.get('name', role)}",
            "",
            f"**Mission.** {first_paragraph(charter, 'Mission') or pack.get('mission', '')}",
            "",
            f"- Pack: [`role-packs/{role}/`](https://github.com/Shashank2577/"
            f"foundry-program/tree/main/role-packs/{role})",
            f"- Skills: {', '.join(f'`{s}`' for s in skills) or '_none_'}",
            f"- Produces: {', '.join(f'`{p}`' for p in pack.get('produces', []))}",
            f"- Bot identity: `{ident.get('git_user', '—')}`"
            + ("" if ident.get("provisioned") else
               " — **not provisioned**, so commits are attributed by the "
               "`Agent-Role:` trailer only, not cryptographically"),
            "",
            "**Forbidden.** " + ", ".join(f"`{f}`" for f in policy.get("forbidden", [])[:8])
            + ("…" if len(policy.get("forbidden", [])) > 8 else ""),
            "",
        ]

    return "\n".join([
        BANNER.format(source="`role-packs/*/` — regenerate with `scripts/build-wiki.py`"),
        "", "# Roles", "",
        "Every role is a versioned pack, not a prompt. Changing how a role "
        "behaves is a pull request against its pack, reviewed like code.",
        "",
        "| Role | Pack | Budget per session | Signing identity |",
        "|---|---|---|---|",
        *rows, "", "---", "", *detail,
    ]) + "\n"


def requirements_page(traceability: dict | None) -> str:
    status_by_req, counts = {}, {}
    if traceability:
        for row in traceability.get("rows", []):
            status_by_req[row["req"]] = row
            counts[row["status"]] = counts.get(row["status"], 0) + 1

    label = {"green": "traced", "amber": "on main, no PR", "red": "untraced"}
    rows = []
    for line in REQ_INDEX.read_text().splitlines():
        m = REQ_ROW.match(line.strip())
        if not m:
            continue
        req, text, section = m.group(1), m.group(2).strip(), m.group(3).strip()
        row = status_by_req.get(req)
        if row:
            state = label.get(row["status"], row["status"])
            prs = ", ".join(f"[#{p['number']}]({p['url']})" for p in row.get("pulls", [])) or "—"
        else:
            state, prs = "unknown", "—"
        rows.append(f"| `{req}` | {text[:110]} | {section} | {state} | {prs} |")

    summary = (", ".join(f"{n} {label.get(k, k)}" for k, n in sorted(counts.items()))
               if counts else "traceability data not available at build time")

    return "\n".join([
        BANNER.format(source="`requirements/index.md` and the traceability generator"),
        "", "# Requirements", "",
        "Every requirement traces to commits and merged pull requests through "
        "the `Requirement:` commit trailer. This table is computed; the live "
        "version with per-commit detail is the "
        "[traceability matrix](https://shashank2577.github.io/foundry-program/traceability.html).",
        "", f"**Current state:** {summary}.", "",
        "| ID | Requirement | PRD § | Status | Merged PRs |",
        "|---|---|---|---|---|",
        *rows, "",
    ]) + "\n"


def home_page(traceability: dict | None) -> str:
    meta = (traceability or {}).get("meta", {})
    counts = {}
    for row in (traceability or {}).get("rows", []):
        counts[row["status"]] = counts.get(row["status"], 0) + 1

    stats = ""
    if counts:
        stats = (f"- **{counts.get('green', 0)}** requirements traced to merged PRs, "
                 f"**{counts.get('amber', 0)}** on `main` without a PR, "
                 f"**{counts.get('red', 0)}** untraced\n"
                 f"- Computed from **{meta.get('commits_scanned', '?')}** commits "
                 f"at `{meta.get('head', '')[:7]}`\n")

    src = WIKI_SRC / "Home.md"
    prose = src.read_text() if src.is_file() else "# Foundry\n"
    return (BANNER.format(source="`wiki/Home.md`") + "\n" + prose
            + "\n## Where the numbers come from\n\n" + stats
            + f"\n_Last generated: {meta.get('generated_at', 'unknown')}._\n")


SIDEBAR = """\
### Foundry

- [[Home]]
- [[Operating-the-System]]
- [[Roles]]
- [[Requirements]]
- [[Conventions]]

### Live

- [Board](https://github.com/users/Shashank2577/projects/2)
- [Traceability](https://shashank2577.github.io/foundry-program/traceability.html)
- [Standup](https://shashank2577.github.io/foundry-program/standup.html)
- [Repository](https://github.com/Shashank2577/foundry-program)
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--traceability", type=Path,
                    default=REPO_ROOT / "dashboards" / "site" / "traceability.json")
    args = ap.parse_args()

    traceability = None
    if args.traceability.is_file():
        traceability = json.loads(args.traceability.read_text())
    else:
        print(f"build-wiki: {args.traceability} not found — the Requirements page "
              "will show `unknown` rather than inventing a status", file=sys.stderr)

    args.out.mkdir(parents=True, exist_ok=True)

    # Hand-written prose pages, copied verbatim with the banner prepended.
    copied = []
    for src in sorted(WIKI_SRC.glob("*.md")):
        if src.name == "Home.md":
            continue
        (args.out / src.name).write_text(
            BANNER.format(source=f"`wiki/{src.name}`") + "\n" + src.read_text())
        copied.append(src.name)

    (args.out / "Home.md").write_text(home_page(traceability))
    (args.out / "Roles.md").write_text(roles_page())
    (args.out / "Requirements.md").write_text(requirements_page(traceability))
    (args.out / "_Sidebar.md").write_text(SIDEBAR)

    pages = sorted(p.name for p in args.out.glob("*.md"))
    print(f"wiki: {len(pages)} page(s) -> {args.out}")
    for p in pages:
        print(f"  {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
