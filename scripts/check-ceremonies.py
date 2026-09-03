#!/usr/bin/env python3
"""Validate `ceremonies/*.yaml` against the schema in `ceremonies/README.md`.

That README is the schema of record; this script enforces it, it does not
redefine it. Every ceremony file carries exactly eight keys — no more, no
fewer — and a handful of value-level rules (see the README's "Schema"
section for the authoritative list).

Every file is checked and every violation is collected before printing, so
a PR fixing one ceremony sees every other problem in the same run rather
than discovering them one push at a time (README: "not fail-fast on the
first file").

    check-ceremonies.py                  # checks ceremonies/ against role-packs/
    check-ceremonies.py --dir fixtures --packs-dir fixtures/packs

Exit 0 if every file is clean, 1 otherwise.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("check-ceremonies: PyYAML is required")

REPO_ROOT = Path(__file__).resolve().parent.parent
CEREMONIES_DIR = REPO_ROOT / "ceremonies"
PACKS_DIR = REPO_ROOT / "role-packs"

REQUIRED_KEYS = {
    "ceremony", "cadence", "role", "consumes", "produces",
    "artifact_is", "escalates_when", "owner",
}
NON_EMPTY_LIST_KEYS = ("consumes", "produces", "escalates_when")
ARTIFACT_KINDS = {"issue comment", "dashboard page", "new issues", "label change"}


def known_roles(packs_dir: Path) -> set[str]:
    """The real pack names, read from the filesystem.

    Not hardcoded: a ninth pack should not require editing this checker
    (ceremonies/README.md).
    """
    if not packs_dir.is_dir():
        return set()
    return {p.name for p in packs_dir.iterdir() if p.is_dir()}


def load_ceremony(path: Path) -> tuple[dict | None, list[str]]:
    """Parse one file. Returns (data, errors) — data is None on any error."""
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        return None, [f"{path.name}: YAML parse error — {exc}"]
    if not isinstance(data, dict):
        return None, [f"{path.name}: does not parse to a mapping of keys"]
    return data, []


def validate_ceremony(path: Path, data: dict, roles: set[str]) -> list[str]:
    """Structural and value checks for a single already-parsed ceremony."""
    errors = []
    name = path.name
    keys = set(data.keys())

    missing = REQUIRED_KEYS - keys
    if missing:
        errors.append(f"{name}: missing required key(s): {', '.join(sorted(missing))}")

    unknown = keys - REQUIRED_KEYS
    if unknown:
        errors.append(f"{name}: unknown key(s): {', '.join(sorted(unknown))}")

    if "role" in data:
        role = data["role"]
        if role not in roles:
            errors.append(
                f"{name}: role '{role}' does not name a real pack under role-packs/"
            )

    if "artifact_is" in data:
        artifact = data["artifact_is"]
        if artifact not in ARTIFACT_KINDS:
            errors.append(
                f"{name}: artifact_is '{artifact}' is not one of "
                f"{sorted(ARTIFACT_KINDS)}"
            )

    for key in NON_EMPTY_LIST_KEYS:
        if key not in data:
            continue
        value = data[key]
        if not isinstance(value, list) or len(value) == 0:
            errors.append(f"{name}: '{key}' must be a non-empty list")

    return errors


def validate_all(ceremonies_dir: Path, packs_dir: Path) -> list[str]:
    """Every violation across every `*.yaml` file in `ceremonies_dir`."""
    errors: list[str] = []
    roles = known_roles(packs_dir)
    files = sorted(ceremonies_dir.glob("*.yaml"))
    if not files:
        return [f"{ceremonies_dir}: no ceremony declarations found"]

    cadence_owner: dict[str, str] = {}
    for path in files:
        data, parse_errors = load_ceremony(path)
        if parse_errors:
            errors.extend(parse_errors)
            continue

        errors.extend(validate_ceremony(path, data, roles))

        cadence = data.get("cadence")
        if isinstance(cadence, str) and cadence:
            if cadence in cadence_owner:
                errors.append(
                    f"{path.name}: cadence '{cadence}' collides with "
                    f"{cadence_owner[cadence]}"
                )
            else:
                cadence_owner[cadence] = path.name

    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", type=Path, default=CEREMONIES_DIR,
                     help="directory of ceremony *.yaml files")
    ap.add_argument("--packs-dir", type=Path, default=PACKS_DIR,
                     help="directory of role-packs/ to validate `role` against")
    args = ap.parse_args()

    errors = validate_all(args.dir, args.packs_dir)
    if errors:
        print(f"check-ceremonies: {len(errors)} violation(s):")
        for error in errors:
            print(f"  - {error}")
        return 1

    count = len(list(args.dir.glob("*.yaml")))
    print(f"check-ceremonies: {count} declaration(s) OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
