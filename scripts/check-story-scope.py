#!/usr/bin/env python3
"""Check that a story's acceptance criteria name only paths its assigned
role's pack can write.

Six stories (#52, #103, #114, #116, #121, #159) demanded a path the
assigned role's `write_scope` denies. Every session refused correctly,
left a box unticked, and escalated — which is the right behaviour, but it
means the DoD check finds the problem only after a session has already
spent its budget discovering it. This is the same question, asked at
refinement instead: for each path named in the acceptance criteria, is it
inside `role-packs/<assigned role>/policy.yaml`'s `write_scope.allow`?

    check-story-scope.py --issue 168
    check-story-scope.py --issue 168 --role developer     # replay under a
                                                            # different role
    check-story-scope.py --role developer < body.txt      # stdin, no tracker call
    check-story-scope.py --issue 168 --comment            # post the report

Reuses `gate-check.py`'s `role_can_write`/`role_of_labels` rather than a
second scope matcher — two matchers that can disagree about who may write
what is worse than none.

Deliberately under-matches. It only reads the acceptance-criteria section
(a Markdown `## Acceptance criteria` heading, or the plain-text
`Acceptance criteria:` line this repo also uses), because that is what the
story asks of the assigned role — the `## Scope` prose above it and
anything below the next heading (`## Out of scope`, `## Notes`) routinely
name paths that are being *read*, cited as precedent, or explicitly
excluded, not demanded. Within that section it extracts only path-like
tokens that end in a known code/config extension or a glob (`policies/**`),
and it drops a token immediately preceded by a reference word ("from",
"matches", "reuses", "per", ...) since those name a file the criterion
reads or imitates, not one it writes. A bare directory mention
(`` `ceremonies/` ``, `` `prds/` ``) is dropped too: naming a directory is
not proposing to write a specific file in it. All of this trades recall
for precision on purpose — a false positive on every story is the gate
nobody reads, and this repo has already shipped that twice (`gate-check.py`,
`policies/gates.yaml`'s own history).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKS_DIR = REPO_ROOT / "role-packs"

_spec = importlib.util.spec_from_file_location("gate_check", Path(__file__).resolve().parent / "gate-check.py")
gate_check = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("gate_check", gate_check)
_spec.loader.exec_module(gate_check)


# --------------------------------------------------------------------------
# Section extraction — pure. Story body in, the acceptance-criteria text out.
# --------------------------------------------------------------------------

_HEADING_AC = re.compile(r"^#{1,6}\s*acceptance criteria\s*$", re.IGNORECASE | re.MULTILINE)
_GHERKIN_AC = re.compile(r"^acceptance criteria:?\s*$", re.IGNORECASE | re.MULTILINE)
_ANY_HEADING = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)


def acceptance_criteria_section(body: str) -> str | None:
    """The text between the acceptance-criteria heading and the next
    heading (or end of body). None if no such heading exists — an
    unparseable body is reported as such, not guessed at.
    """
    for pattern in (_HEADING_AC, _GHERKIN_AC):
        m = pattern.search(body or "")
        if m:
            nxt = _ANY_HEADING.search(body, m.end())
            return body[m.end(): nxt.start() if nxt else len(body)]
    return None


# --------------------------------------------------------------------------
# Path extraction — pure. Text in, path-like tokens out.
# --------------------------------------------------------------------------

KNOWN_EXTENSIONS = ("py", "sh", "ya?ml", "js", "ts", "jsx", "tsx", "go", "rb")

# A reference word immediately before a path means the criterion reads or
# imitates that path, not that it writes it — "from `policies/gates.yaml`",
# "vocabulary matches `policies/gates.yaml`".
_REFERENCE_WORDS = {
    "from", "matches", "matching", "reuses", "reuse", "reusing", "per",
    "against", "see", "cf", "compare", "reads", "read", "reading",
}

_PATH_RE = re.compile(
    r"(?<![\w/])"
    r"(?:[A-Za-z0-9_.-]+/)+"                         # one or more dir segments
    r"(?:[A-Za-z0-9_.-]*\*[A-Za-z0-9_.*-]*"           # a glob final segment ...
    rf"|[A-Za-z0-9_.-]+\.(?:{'|'.join(KNOWN_EXTENSIONS)}))"  # ... or file.ext
    r"(?![\w/])"
)


def _preceding_word(text: str, idx: int) -> str:
    prefix = text[:idx].rstrip("`\"'( \t")
    m = re.search(r"([A-Za-z]+)\s*$", prefix)
    return m.group(1).lower() if m else ""


def extract_paths(text: str) -> list[str]:
    """Path-like tokens named in `text`, in first-seen order, deduplicated.

    See the module docstring for exactly what is deliberately dropped.
    """
    seen: list[str] = []
    for m in _PATH_RE.finditer(text or ""):
        if _preceding_word(text, m.start()) in _REFERENCE_WORDS:
            continue
        path = m.group(0)
        if path not in seen:
            seen.append(path)
    return seen


# --------------------------------------------------------------------------
# Scope analysis — pure. Paths and a role in, a verdict out.
# --------------------------------------------------------------------------

def all_roles(packs_dir: Path = PACKS_DIR) -> list[str]:
    return sorted(p.parent.name for p in packs_dir.glob("*/policy.yaml"))


def capable_roles(path: str, packs_dir: Path = PACKS_DIR) -> list[str]:
    """Every role whose own pack could write `path` — not just the one
    assigned. Used both to name who could have done the work, and to
    detect a story spanning more than one role's scope.
    """
    return [r for r in all_roles(packs_dir)
            if gate_check.role_can_write(r, [path], packs_dir)]


def analyze(body: str, role: str | None, packs_dir: Path = PACKS_DIR) -> dict:
    """Pure. A story body and its assigned role in, a verdict out.

    Fields:
      section       — the acceptance-criteria text found, or None (unparseable)
      role          — the role passed in, possibly None (no role label)
      paths         — every path-like token found, each with its capable roles
      out_of_scope  — paths the assigned role cannot write (empty if role is None)
      spanning      — roles whose scopes are jointly required to cover every
                       path, when no single role covers them all; empty otherwise
      flagged       — True if out_of_scope or spanning is non-empty
    """
    section = acceptance_criteria_section(body)
    if section is None:
        return {"section": None, "role": role, "paths": [],
                "out_of_scope": [], "spanning": [], "flagged": False}

    paths = extract_paths(section)
    entries = [{"path": p, "capable_roles": capable_roles(p, packs_dir)} for p in paths]

    out_of_scope = []
    if role:
        for e in entries:
            if not gate_check.role_can_write(role, [e["path"]], packs_dir):
                out_of_scope.append(e)

    owned = [e["capable_roles"] for e in entries if e["capable_roles"]]
    spanning: list[str] = []
    if len(owned) >= 2 and not set.intersection(*(set(o) for o in owned)):
        spanning = sorted(set().union(*owned))

    return {
        "section": section, "role": role, "paths": entries,
        "out_of_scope": out_of_scope, "spanning": spanning,
        "flagged": bool(out_of_scope or spanning),
    }


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def render_report(result: dict, issue: int | None) -> str:
    header = f"### Story-scope check{f' — #{issue}' if issue else ''}"
    lines = [header, ""]

    if result["section"] is None:
        lines.append("No `## Acceptance criteria` section (or `Acceptance criteria:` "
                      "block) was found — nothing to check. This is reported, not "
                      "guessed at.")
        return "\n".join(lines) + "\n"

    if not result["role"]:
        lines.append("No single `role:*` label found — the assigned role cannot be "
                      "determined, so out-of-scope paths cannot be checked against it.")
        lines.append("")

    if result["role"] and not result["out_of_scope"]:
        lines.append(f"Every path named in the acceptance criteria is inside "
                      f"`role-packs/{result['role']}/policy.yaml`'s write scope.")
        lines.append("")

    for e in result["out_of_scope"]:
        who = ", ".join(f"`{r}`" for r in e["capable_roles"]) or "no role's pack"
        lines.append(f"- `{e['path']}` is not in `role-packs/{result['role']}/policy.yaml`'s "
                      f"write scope. {who} can write it.")

    if result["spanning"]:
        lines.append("")
        lines.append(f"- This story's acceptance criteria span more than one role's "
                      f"write scope — {', '.join(f'`{r}`' for r in result['spanning'])} "
                      "are jointly needed to cover every path named, even where the "
                      "assigned role covers some of them. Consider splitting it.")

    if result["flagged"]:
        lines.append("")
        lines.append("_Mechanical check against `write_scope.allow`/`deny`. Extraction "
                      "deliberately under-matches — see `check-story-scope.py`'s module "
                      "docstring for what it ignores. A false positive here is worth "
                      "saying so on the issue._")

    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# The world
# --------------------------------------------------------------------------

def gh(args: list[str]) -> str:
    return subprocess.run(["gh", *args], cwd=REPO_ROOT, check=True,
                          capture_output=True, text=True).stdout


def read_issue(number: int) -> dict:
    return json.loads(gh(["issue", "view", str(number), "--json", "number,title,body,labels"]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--issue", type=int, help="work item to read from the tracker")
    ap.add_argument("--role", help="assigned role; overrides the issue's role:* label "
                                    "(required in stdin mode)")
    ap.add_argument("--comment", action="store_true",
                    help="post the report to the issue (requires --issue)")
    args = ap.parse_args()

    if args.issue:
        issue = read_issue(args.issue)
        body = issue.get("body") or ""
        labels = [lbl["name"] for lbl in issue.get("labels", [])]
        role = args.role or gate_check.role_of_labels(labels, "role:")
    else:
        if not args.role:
            sys.exit("check-story-scope: --role is required when reading from stdin")
        body = sys.stdin.read()
        role = args.role

    result = analyze(body, role)
    report = render_report(result, args.issue)
    print(report)

    if args.comment:
        if not args.issue:
            sys.exit("check-story-scope: --comment requires --issue")
        note = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "story-scope-note.md"
        note.write_text(report)
        gh(["issue", "comment", str(args.issue), "--body-file", str(note)])

    return 1 if result["flagged"] else 0


if __name__ == "__main__":
    sys.exit(main())
