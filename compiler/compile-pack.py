#!/usr/bin/env python3
"""Compile a harness-neutral role pack into harness-specific config.

PRD §3: role packs are neutral; a compiler renders them per harness.
This is the v0 compiler. It knows one harness properly (claude-code) and
degrades honestly for the others rather than pretending.

    compile-pack.py --role developer --check
    compile-pack.py --role developer --harness claude-code --out build/

Requires PyYAML (present on GitHub-hosted ubuntu runners).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - environment problem, not logic
    sys.exit("compile-pack: PyYAML is required (pip install pyyaml)")

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKS_DIR = REPO_ROOT / "role-packs"

REQUIRED_FILES = ("pack.yaml", "charter.md", "tools.yaml", "policy.yaml")
REQUIRED_PACK_KEYS = ("version", "role", "harness_compat", "identity")
REQUIRED_POLICY_KEYS = ("budgets", "forbidden", "hitl_triggers", "escalation")
REQUIRED_BUDGET_KEYS = ("turns", "cost_usd", "tokens", "wall_clock_minutes",
                        "max_retries")


class PackError(Exception):
    """A pack is malformed. Always fatal — a half-valid pack is worse."""


def load(path: Path):
    try:
        return yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise PackError(f"{path.relative_to(REPO_ROOT)}: invalid YAML — {exc}")


def read_pack(role: str) -> dict:
    """Load and validate one pack. Raises PackError with a specific reason."""
    root = PACKS_DIR / role
    if not root.is_dir():
        raise PackError(f"no role pack at role-packs/{role}/")

    missing = [f for f in REQUIRED_FILES if not (root / f).is_file()]
    if missing:
        raise PackError(f"role-packs/{role}/ is missing {', '.join(missing)}")

    pack = load(root / "pack.yaml") or {}
    policy = load(root / "policy.yaml") or {}
    tools = load(root / "tools.yaml") or {}

    for key in REQUIRED_PACK_KEYS:
        if key not in pack:
            raise PackError(f"role-packs/{role}/pack.yaml: missing `{key}`")
    if not (pack.get("identity") or {}).get("token_secret"):
        raise PackError(
            f"role-packs/{role}/pack.yaml: identity.token_secret is missing — "
            "a role nobody can authenticate is not dispatchable"
        )
    if pack.get("role") != role:
        raise PackError(
            f"role-packs/{role}/pack.yaml: role is `{pack.get('role')}`, "
            f"but the directory says `{role}`"
        )

    for key in REQUIRED_POLICY_KEYS:
        if key not in policy:
            raise PackError(f"role-packs/{role}/policy.yaml: missing `{key}`")
    for key in REQUIRED_BUDGET_KEYS:
        if key not in (policy.get("budgets") or {}):
            raise PackError(
                f"role-packs/{role}/policy.yaml: budgets is missing `{key}` — "
                "an unbudgeted role cannot be dispatched"
            )

    template = policy.get("escalation", {}).get("template")
    if template and not (REPO_ROOT / template).is_file():
        raise PackError(
            f"role-packs/{role}/policy.yaml: escalation.template points at "
            f"`{template}`, which does not exist"
        )

    skills = sorted((root / "skills").glob("*.md")) if (root / "skills").is_dir() else []
    return {
        "role": role,
        "root": root,
        "pack": pack,
        "policy": policy,
        "tools": tools,
        "token_secret": pack["identity"]["token_secret"],
        "charter": (root / "charter.md").read_text(),
        "skills": [(p.stem, p.read_text()) for p in skills],
    }


def to_bash_rule(pattern: str) -> str | None:
    """Map a neutral shell glob onto a Claude Code Bash permission rule.

    Claude Code matches on a command prefix, so only patterns that are a
    literal prefix optionally followed by `*` can be expressed. Anything
    with an interior wildcard is returned as None and reported, never
    silently dropped — a permission rule that quietly did not compile is
    the worst possible outcome for a security control.
    """
    body = pattern[:-1] if pattern.endswith("*") else pattern
    if "*" in body:
        return None
    return f"Bash({body}:*)" if pattern.endswith("*") else f"Bash({body})"


def compile_claude_code(pack: dict) -> dict[str, str]:
    """Render a pack as a Claude Code system prompt plus settings.json."""
    policy, tools = pack["policy"], pack["tools"]
    budgets = policy["budgets"]
    role = pack["role"]

    parts = [
        f"# Role: {role}",
        "",
        pack["charter"].strip(),
        "",
        "---",
        "",
        "# Budget",
        "",
        f"- Turns: {budgets['turns']}",
        f"- Cost ceiling: ${budgets['cost_usd']}",
        f"- Tokens: {budgets['tokens']:,} (reported, not enforced)",
        f"- Wall clock: {budgets['wall_clock_minutes']} minutes",
        f"- Retries: {budgets['max_retries']}",
        f"- On breach: {budgets.get('on_breach', 'escalate')} — never a silent stop.",
        "",
        "# Forbidden actions",
        "",
    ]
    parts += [f"- {a}" for a in policy["forbidden"]]
    parts += ["", "# Escalate to a human when", ""]
    parts += [f"- {t}" for t in policy["hitl_triggers"]]

    for name, body in pack["skills"]:
        parts += ["", "---", "", f"# Skill: {name}", "", body.strip()]

    allow, deny, unmappable = [], [], []
    for pattern in (tools.get("shell", {}) or {}).get("allow", []):
        rule = to_bash_rule(pattern)
        (allow if rule else unmappable).append(rule or f"allow:{pattern}")
    for pattern in (tools.get("shell", {}) or {}).get("deny", []):
        rule = to_bash_rule(pattern)
        (deny if rule else unmappable).append(rule or f"deny:{pattern}")

    # bypassPermissions, not acceptEdits. A prompt in a headless session is a
    # denial, and an allowlist cannot enumerate a shell: two runs burned their
    # whole budget on 27 denials each, including `claude --version`, which the
    # charter instructs the agent to run.
    #
    # The allow list stays — it documents the happy path and is what a second
    # harness would compile from — but the controls that actually hold are the
    # deny list, branch protection with admin enforcement, and the token's
    # scope. None of those depend on the allowlist being complete.
    settings = {
        "permissions": {
            "allow": allow,
            "deny": deny,
            "defaultMode": "bypassPermissions",
        },
    }

    out = {
        "system-prompt.md": "\n".join(parts).rstrip() + "\n",
        "settings.json": json.dumps(settings, indent=2) + "\n",
        # The dispatcher reads this to pick the role's credential rather
        # than carrying a role->secret table of its own.
        "token-secret": pack["token_secret"] + "\n",
    }
    if unmappable:
        out["UNMAPPABLE.md"] = (
            "# Rules this harness cannot express\n\n"
            "Claude Code matches Bash permissions on a command prefix, so a\n"
            "pattern with an interior wildcard has no equivalent. These are\n"
            "listed rather than dropped. Each one needs a structural control\n"
            "(branch protection, a required check) to actually hold.\n\n"
            + "".join(f"- `{u}`\n" for u in unmappable)
        )
    return out


HARNESSES = {"claude-code": compile_claude_code}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--role", help="role to compile; omit with --check for all")
    ap.add_argument("--harness", default="claude-code", choices=sorted(HARNESSES))
    ap.add_argument("--out", type=Path, help="output directory")
    ap.add_argument("--check", action="store_true", help="validate only, write nothing")
    args = ap.parse_args()

    if args.check and not args.role:
        roles = sorted(p.name for p in PACKS_DIR.iterdir() if (p / "pack.yaml").is_file())
        if not roles:
            print("no role packs found — nothing to check")
            return 0
    elif args.role:
        roles = [args.role]
    else:
        ap.error("--role is required unless --check is given")

    failures = 0
    for role in roles:
        try:
            pack = read_pack(role)
        except PackError as exc:
            print(f"FAIL {role}: {exc}", file=sys.stderr)
            failures += 1
            continue

        compat = pack["pack"].get("harness_compat", {}).get(args.harness, {})
        if not compat.get("supported"):
            print(f"FAIL {role}: pack.yaml does not support harness `{args.harness}`",
                  file=sys.stderr)
            failures += 1
            continue

        artifacts = HARNESSES[args.harness](pack)
        skills = len(pack["skills"])
        unmappable = "UNMAPPABLE.md" in artifacts

        if args.check:
            print(f"ok   {role}: {len(artifacts)} artifact(s) for {args.harness}, "
                  f"{skills} skill(s)"
                  + (", some tool rules unmappable (see --out)" if unmappable else ""))
            continue

        dest = (args.out or REPO_ROOT / "build" / "packs") / role / args.harness
        dest.mkdir(parents=True, exist_ok=True)
        for name, content in artifacts.items():
            (dest / name).write_text(content)
        print(f"compiled {role} -> {dest} ({', '.join(sorted(artifacts))})")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
