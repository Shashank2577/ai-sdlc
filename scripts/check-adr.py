#!/usr/bin/env python3
"""Validate adrs/*.md against role-packs/architect/templates/adr.md's format.

The template uses inline bold fields (`**Status:**`, `**Work item:**`,
`**Requirement:**`), not YAML frontmatter — this reads that format as-is
rather than imposing a new schema.

    check-adr.py                  # validate adrs/
    check-adr.py --dir path/to/fixtures

Exits 0 with no output when every record is clean. Otherwise prints every
violation found (not just the first — a validator that stops at one error
takes N runs to fix N problems) and exits 1.

Checked, per ADR file:
  - filename matches NNNN-title-in-kebab-case.md
  - `# ADR-NNNN: <title>` heading present, its number matching the filename
  - **Status:**, **Work item:**, **Requirement:** fields all present
  - **Status:** is `proposed`, `accepted`, or `superseded by ADR-NNNN`
    referencing another ADR that actually exists in the directory
  - **Work item:** looks like `<owner>/<repo>#<issue>` (comma-separated
    extra `#<issue>` refs allowed) — shape only. Confirming the issue
    itself exists would mean calling the GitHub API from a validator that
    runs offline, so this stays offline-checkable by design.
  - **Requirement:** looks like `REQ-0XX` (comma-separated list allowed)

Checked across the whole set:
  - no two files claim the same ADR number
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ADRS_DIR = REPO_ROOT / "adrs"

FILENAME_RE = re.compile(r"^(\d{4})-[a-z0-9-]+\.md$")
HEADING_RE = re.compile(r"^#\s*ADR-(\d{4}):\s*\S.*$", re.MULTILINE)
STATUS_RE = re.compile(r"^\*\*Status:\*\*\s*(.+)$", re.MULTILINE)
WORK_ITEM_RE = re.compile(r"^\*\*Work item:\*\*\s*(.+)$", re.MULTILINE)
REQUIREMENT_RE = re.compile(r"^\*\*Requirement:\*\*\s*(.+)$", re.MULTILINE)

SUPERSEDED_RE = re.compile(r"^superseded by ADR-(\d{4})$")
VALID_STATUSES = {"proposed", "accepted"}

# Shape only — an owner/repo#issue reference, with optional bare "#issue"
# extras for the multi-issue case (see adrs/0005's "…#75, #79").
WORK_ITEM_REF_RE = re.compile(r"^[\w.-]+/[\w.-]+#\d+(\s*,\s*#\d+)*$")
REQUIREMENT_REF_RE = re.compile(r"^REQ-\d{3}(\s*,\s*REQ-\d{3})*$")


def parse(path: Path) -> tuple[dict, list[str]]:
    """Parse one ADR file. Returns (fields, violations) for that file alone;
    cross-file checks (duplicates, dangling supersedes) happen in validate()."""
    violations: list[str] = []
    text = path.read_text()
    name = path.name

    m = FILENAME_RE.match(name)
    file_number = m.group(1) if m else None
    if not m:
        violations.append(
            f"{name}: filename does not match NNNN-title-in-kebab-case.md"
        )

    hm = HEADING_RE.search(text)
    heading_number = hm.group(1) if hm else None
    if not hm:
        violations.append(f"{name}: missing `# ADR-NNNN: <title>` heading")
    elif file_number and heading_number != file_number:
        violations.append(
            f"{name}: heading number ADR-{heading_number} does not match "
            f"filename number {file_number}"
        )

    number = heading_number or file_number

    sm = STATUS_RE.search(text)
    status = sm.group(1).strip() if sm else None
    if not sm:
        violations.append(f"{name}: missing **Status:** field")

    wm = WORK_ITEM_RE.search(text)
    work_item = wm.group(1).strip() if wm else None
    if not wm:
        violations.append(f"{name}: missing **Work item:** field")
    elif not WORK_ITEM_REF_RE.match(work_item):
        violations.append(
            f"{name}: **Work item:** {work_item!r} is not a well-formed "
            f"<owner>/<repo>#<issue#> reference"
        )

    rm = REQUIREMENT_RE.search(text)
    requirement = rm.group(1).strip() if rm else None
    if not rm:
        violations.append(f"{name}: missing **Requirement:** field")
    elif not REQUIREMENT_REF_RE.match(requirement):
        violations.append(
            f"{name}: **Requirement:** {requirement!r} is not a well-formed "
            f"REQ-0XX reference"
        )

    return {"path": path, "number": number, "status": status}, violations


def validate(adrs_dir: Path) -> list[str]:
    if not adrs_dir.is_dir():
        return [f"{adrs_dir}: not a directory"]

    files = sorted(
        p for p in adrs_dir.glob("*.md") if p.name.lower() != "readme.md"
    )

    violations: list[str] = []
    records = []
    numbers_seen: dict[str, list[str]] = {}

    for path in files:
        fields, file_violations = parse(path)
        violations.extend(file_violations)
        records.append(fields)
        if fields["number"]:
            numbers_seen.setdefault(fields["number"], []).append(path.name)

    for number, names in sorted(numbers_seen.items()):
        if len(names) > 1:
            violations.append(
                f"ADR-{number}: claimed by more than one file: "
                f"{', '.join(sorted(names))}"
            )

    known_numbers = set(numbers_seen)

    for fields in records:
        status = fields["status"]
        if status is None:
            continue  # already reported as a missing field
        name = fields["path"].name
        sm = SUPERSEDED_RE.match(status)
        if sm:
            target = sm.group(1)
            if target == fields["number"]:
                violations.append(
                    f"{name}: **Status:** cannot mark ADR-{target} as "
                    f"superseded by itself"
                )
            elif target not in known_numbers:
                violations.append(
                    f"{name}: **Status:** references ADR-{target}, which "
                    f"does not exist"
                )
        elif status not in VALID_STATUSES:
            violations.append(
                f"{name}: **Status:** {status!r} is not one of "
                f"'proposed', 'accepted', or 'superseded by ADR-NNNN'"
            )

    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dir",
        type=Path,
        default=ADRS_DIR,
        help="directory of ADR records to validate (default: adrs/)",
    )
    args = parser.parse_args(argv)

    violations = validate(args.dir)
    if violations:
        for v in violations:
            print(f"FAIL: {v}", file=sys.stderr)
        print(f"\n{len(violations)} violation(s) in {args.dir}", file=sys.stderr)
        return 1

    print(f"OK: every ADR record in {args.dir} is valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
