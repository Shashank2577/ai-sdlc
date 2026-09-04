#!/usr/bin/env python3
"""Validate policies/environments.yaml against the template's own contract
and against the platform it describes but does not enforce.

`policies/environments.yaml` says plainly that it is "only honest for as
long as `scripts/check-environments.py` keeps verifying it against the
live repo" — a declared ladder with no platform behind it is exactly the
kind of flattery REQ-010 keeps attracting, and two earlier proxies for it
were rejected on those grounds. So this checks two independent things:

Structural (offline, no API call):
  - `promotion_order` names exactly the environments declared, no
    duplicates, and each environment's `promotes_from`/`promotes_to`
    agrees with its neighbours in that order — a total order with no
    cycle, checked by consistency rather than by graph search, because a
    plain list cannot represent a cycle that this check would miss.
  - every environment declares a non-empty `rollback.owner`

Platform (queries `GET /repos/{owner}/{repo}/environments`):
  - every environment named in the policy exists on the repo
  - every environment marked `human_reviewer_required: true` has an
    actual `required_reviewers` protection rule with at least one
    reviewer configured — the policy describes this, the platform is
    supposed to enforce it, and this is what confirms it actually does

    check-environments.py                       # validate the real policy against the real repo
    check-environments.py --policy path/to.yaml --repo owner/name

Reports every violation found, not just the first, and exits non-zero on
any. Exits 0 with no violations printed only when both checks are clean.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_POLICY = REPO_ROOT / "policies" / "environments.yaml"


def load_policy(path: Path) -> dict:
    try:
        import yaml
    except ImportError:  # pragma: no cover
        sys.exit("check-environments: PyYAML is required")
    if not path.is_file():
        sys.exit(f"check-environments: {path} not found — the ladder policy is the policy")
    return yaml.safe_load(path.read_text()) or {}


# --------------------------------------------------------------------------
# Structural — pure. The policy file in, violations out. No API call.
# --------------------------------------------------------------------------

def validate_structure(policy: dict) -> list[str]:
    violations: list[str] = []
    environments = policy.get("environments") or {}
    promotion_order = policy.get("promotion_order") or []

    if not environments:
        return ["policy declares no `environments`"]

    for name, env in environments.items():
        owner = ((env or {}).get("rollback") or {}).get("owner")
        if not owner or not str(owner).strip():
            violations.append(f"{name}: no `rollback.owner` declared")

    names = set(environments)
    order_set = set(promotion_order)

    if len(promotion_order) != len(order_set):
        seen: set[str] = set()
        dupes = sorted({n for n in promotion_order if n in seen or seen.add(n)})
        violations.append(f"promotion_order contains duplicate entries: {dupes}")
        return violations  # chain checks below assume a set-like order

    missing = sorted(names - order_set)
    if missing:
        violations.append(f"promotion_order is missing environment(s): {missing}")

    extra = sorted(order_set - names)
    if extra:
        violations.append(
            f"promotion_order names environment(s) not declared under "
            f"`environments`: {extra}"
        )

    if missing or extra:
        return violations  # the chain below is meaningless until this matches

    for i, name in enumerate(promotion_order):
        env = environments[name]
        expected_prev = promotion_order[i - 1] if i > 0 else None
        expected_next = promotion_order[i + 1] if i < len(promotion_order) - 1 else None
        actual_prev = env.get("promotes_from")
        actual_next = env.get("promotes_to")
        if actual_prev != expected_prev:
            violations.append(
                f"{name}: promotes_from is {actual_prev!r}, expected "
                f"{expected_prev!r} per promotion_order — not a total order "
                f"(or a cycle back into the chain)"
            )
        if actual_next != expected_next:
            violations.append(
                f"{name}: promotes_to is {actual_next!r}, expected "
                f"{expected_next!r} per promotion_order — not a total order "
                f"(or a cycle back into the chain)"
            )

    return violations


# --------------------------------------------------------------------------
# Platform — the policy's claims checked against what the API returns.
# --------------------------------------------------------------------------

def validate_platform(environments: dict, api_environments: dict) -> list[str]:
    violations: list[str] = []
    for name, env in environments.items():
        api_env = api_environments.get(name)
        if api_env is None:
            violations.append(
                f"{name}: declared in policy but does not exist on the repo "
                f"(GET /repos/{{owner}}/{{repo}}/environments)"
            )
            continue
        if (env or {}).get("human_reviewer_required"):
            reviewers = [
                r
                for rule in api_env.get("protection_rules", [])
                if rule.get("type") == "required_reviewers"
                for r in rule.get("reviewers", [])
            ]
            if not reviewers:
                violations.append(
                    f"{name}: policy sets human_reviewer_required: true but "
                    f"the repo has no required-reviewers protection rule "
                    f"configured — a workflow targeting it would not pause"
                )
    return violations


# --------------------------------------------------------------------------
# The world — gh api, isolated so tests never call it.
# --------------------------------------------------------------------------

def gh(args: list[str]) -> str:
    return subprocess.run(
        ["gh", *args], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout


def default_repo() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY")
    if repo:
        return repo
    return gh(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"]).strip()


def fetch_platform_environments(repo: str) -> dict:
    """{name: {...}} for every GitHub Environment on `repo`.

    `gh api --paginate` on an object-shaped (not bare-array) response
    prints one JSON document per page back to back rather than merging
    them, so pages are split with a raw decoder instead of `json.loads`
    on the whole stream.
    """
    raw = gh(["api", "--paginate", f"repos/{repo}/environments"]).strip()
    result: dict = {}
    if not raw:
        return result
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(raw):
        while idx < len(raw) and raw[idx].isspace():
            idx += 1
        if idx >= len(raw):
            break
        obj, end = decoder.raw_decode(raw, idx)
        for env in obj.get("environments", []):
            result[env["name"]] = env
        idx = end
    return result


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(
    argv: list[str] | None = None,
    fetch: Callable[[str], dict] = fetch_platform_environments,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--policy", type=Path, default=ENV_POLICY,
                        help="path to the environment ladder policy (default: policies/environments.yaml)")
    parser.add_argument("--repo", default=None,
                        help="owner/repo to query (default: $GITHUB_REPOSITORY, else `gh repo view`)")
    args = parser.parse_args(argv)

    policy = load_policy(args.policy)
    violations = validate_structure(policy)
    if violations:
        for v in violations:
            print(f"FAIL: {v}", file=sys.stderr)
        print(f"\n{len(violations)} violation(s) in {args.policy}", file=sys.stderr)
        return 1

    repo = args.repo or default_repo()
    api_environments = fetch(repo)
    violations = validate_platform(policy.get("environments") or {}, api_environments)
    if violations:
        for v in violations:
            print(f"FAIL: {v}", file=sys.stderr)
        print(f"\n{len(violations)} violation(s) against {repo}", file=sys.stderr)
        return 1

    print(f"OK: every environment in {args.policy} is valid and matches {repo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
