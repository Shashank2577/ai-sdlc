#!/usr/bin/env python3
"""Resolve the budget for a dispatch: role pack policy, then overrides.

Budgets live in `role-packs/<role>/policy.yaml` (PRD §13). The dispatcher
reads them from there rather than carrying its own numbers, so changing a
budget is a reviewed PR against the pack — not a workflow edit.

    read-budget.py --role developer
    read-budget.py --role developer --turns 50        # one-off override
    read-budget.py --role qa --format github          # for $GITHUB_OUTPUT

Precedence: explicit override > role pack policy > built-in default. The
built-in default exists so a role with no pack yet is still budgeted; an
unbudgeted session is the thing this must never allow.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Deliberately conservative. If these are ever what gets used, something
# upstream is missing and the session should be short enough to notice.
DEFAULTS = {
    "turns": 30,
    "tokens": 400_000,
    "wall_clock_minutes": 45,
    "max_retries": 2,
    "on_breach": "escalate",
}

KEY_LINE = re.compile(r"^(\s*)([a-z_]+):\s*(.*?)\s*(?:#.*)?$")


def parse_budgets_fallback(text: str) -> dict:
    """Read the flat `budgets:` block without PyYAML.

    The dispatcher runs on a bare runner, and installing a dependency just
    to read five integers is a failure mode of its own. This handles
    exactly what a budget block is — one flat mapping of scalars — and
    raises on anything else rather than guessing.
    """
    lines = text.splitlines()
    start = None
    indent = 0
    for i, line in enumerate(lines):
        m = KEY_LINE.match(line)
        if m and m.group(2) == "budgets" and not m.group(3):
            start, indent = i + 1, len(m.group(1))
            break
    if start is None:
        raise KeyError("no `budgets:` block")

    out: dict = {}
    for line in lines[start:]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = KEY_LINE.match(line)
        if not m:
            raise ValueError(f"cannot parse budget line: {line!r}")
        pad, key, value = len(m.group(1)), m.group(2), m.group(3)
        if pad <= indent:
            break                      # dedented out of the block
        if not value:
            raise ValueError(f"budget key `{key}` is nested; budgets must be flat")
        out[key] = int(value) if value.isdigit() else value
    if not out:
        raise ValueError("`budgets:` block is empty")
    return out


def read_policy_budgets(role: str) -> tuple[dict, str]:
    """(budgets, source). Missing pack is not an error — it is the v0 state."""
    path = REPO_ROOT / "role-packs" / role / "policy.yaml"
    if not path.is_file():
        return {}, f"built-in defaults (no role-packs/{role}/policy.yaml)"

    text = path.read_text()
    try:
        import yaml
        budgets = (yaml.safe_load(text) or {}).get("budgets") or {}
        if not budgets:
            raise KeyError("no `budgets:` block")
    except ImportError:
        budgets = parse_budgets_fallback(text)
    return budgets, f"role-packs/{role}/policy.yaml"


def resolve(role: str, overrides: dict) -> tuple[dict, str]:
    budgets, source = read_policy_budgets(role)
    resolved = dict(DEFAULTS)
    resolved.update({k: v for k, v in budgets.items() if k in DEFAULTS})
    resolved.update({k: v for k, v in overrides.items() if v})

    for key in ("turns", "tokens", "wall_clock_minutes", "max_retries"):
        try:
            resolved[key] = int(resolved[key])
        except (TypeError, ValueError):
            sys.exit(f"read-budget: `{key}` is not a number: {resolved[key]!r}")
        if resolved[key] < 0:
            sys.exit(f"read-budget: `{key}` must not be negative")
    if resolved["turns"] < 1:
        sys.exit("read-budget: `turns` must be at least 1 — a zero-turn "
                 "session cannot do anything but cost money")
    return resolved, source


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--role", required=True)
    ap.add_argument("--turns", type=int, default=0, help="override; 0 means use policy")
    ap.add_argument("--format", choices=("github", "json", "text"), default="text")
    args = ap.parse_args()

    budget, source = resolve(args.role, {"turns": args.turns})

    if args.format == "json":
        print(json.dumps({**budget, "source": source}))
    elif args.format == "github":
        for key, value in budget.items():
            print(f"{key}={value}")
        print(f"source={source}")
    else:
        print(f"budget for `{args.role}` from {source}:")
        for key, value in budget.items():
            print(f"  {key:20} {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
