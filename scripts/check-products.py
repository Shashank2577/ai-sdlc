#!/usr/bin/env python3
"""Validate policies/products.yaml against the platform it describes but
does not enforce.

`policies/products.yaml` says plainly that every claim it makes — that a
repo exists, that a project board exists, that a repo is genuinely
bootstrapped — is "unverified prose" until this script runs as a required
check. It specifies eight rules under its own `validation:` key; this
implements each one, verbatim.

Structural (offline, no API call — checked against the other policy files
already in this repo):
  - `environments_known` — every entry's `environments[].name` is declared
    in `policies/environments.yaml`
  - `environments_not_weakened` — no entry sets `human_reviewer_required:
    false` on a rung the ladder marks `true`
  - `roles_have_packs` — every entry's `roles[]` name has a matching
    `role-packs/<name>/policy.yaml`
  - `budget_overrides_only_tighten` — every `budget_overrides.<role>.<field>`
    is <= the role pack's own default, and `role` is permitted by the
    entry's own `roles` list when non-empty
  - `no_duplicate_projects` — no two entries share a `{project.owner,
    project.number}`

Platform (queries the GitHub API via `gh`):
  - `repo_resolves` — every entry's `repo` resolves via `GET
    /repos/{repo}` (200, and not a stale name that redirected)
  - `project_resolves` — every entry's `project` resolves via the same
    GraphQL shape `scripts/sync-project.py` uses to load a board
  - `bootstrapped_is_verified` — for `bootstrapped: true` entries,
    CONVENTIONS.md, .github/CODEOWNERS, a PR template, and a required
    status check on the default branch all actually exist on the repo.
    Which context name proves the DoD gate is an optional per-entry
    `dod_check_context` (default `"dod"`, this repo's own context name) —
    checked, not hardcoded, exactly as the policy's own text requires.

Structural violations are reported and the check exits before making any
API call, the same short-circuit `check-environments.py` uses — a policy
that fails its own shape is not worth spending API calls verifying.

    check-products.py                       # validate the real policy
    check-products.py --policy path/to.yaml

Reports every violation found, not just the first, and exits non-zero on
any. Exits 0 with no violations printed only when both passes are clean.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
PRODUCTS_POLICY = REPO_ROOT / "policies" / "products.yaml"
ENV_POLICY = REPO_ROOT / "policies" / "environments.yaml"
ROLE_PACKS_DIR = REPO_ROOT / "role-packs"

DEFAULT_DOD_CONTEXT = "dod"


def load_yaml(path: Path) -> dict:
    try:
        import yaml
    except ImportError:  # pragma: no cover
        sys.exit("check-products: PyYAML is required")
    if not path.is_file():
        sys.exit(f"check-products: {path} not found")
    return yaml.safe_load(path.read_text()) or {}


# --------------------------------------------------------------------------
# Structural — pure. The policy files in, violations out. No API call.
# --------------------------------------------------------------------------

def validate_environments_known(products: dict, known_envs: set) -> list[str]:
    violations = []
    for key, entry in products.items():
        for env in (entry or {}).get("environments") or []:
            name = env.get("name")
            if name not in known_envs:
                violations.append(
                    f"{key}: environment {name!r} is not declared under "
                    f"`environments` in policies/environments.yaml"
                )
    return violations


def validate_environments_not_weakened(products: dict, ladder_environments: dict) -> list[str]:
    violations = []
    for key, entry in products.items():
        for env in (entry or {}).get("environments") or []:
            name = env.get("name")
            ladder_env = ladder_environments.get(name)
            if ladder_env is None:
                continue  # environments_known already reports an unknown name
            if ladder_env.get("human_reviewer_required") and env.get("human_reviewer_required") is False:
                violations.append(
                    f"{key}: sets human_reviewer_required: false on {name!r}, "
                    f"which policies/environments.yaml marks true — a product "
                    f"may tighten a rung, never weaken it"
                )
    return violations


def validate_roles_have_packs(products: dict, role_pack_names: set) -> list[str]:
    violations = []
    for key, entry in products.items():
        for role in (entry or {}).get("roles") or []:
            if role not in role_pack_names:
                violations.append(
                    f"{key}: role {role!r} has no role-packs/{role}/policy.yaml"
                )
    return violations


def validate_budget_overrides(products: dict, role_pack_budgets: dict) -> list[str]:
    violations = []
    for key, entry in products.items():
        entry = entry or {}
        roles = entry.get("roles") or []
        overrides = entry.get("budget_overrides") or {}
        for role, fields in overrides.items():
            if roles and role not in roles:
                violations.append(
                    f"{key}: budget_overrides sets {role!r} but this entry's "
                    f"`roles` list ({roles}) does not permit that role"
                )
            defaults = role_pack_budgets.get(role)
            if defaults is None:
                violations.append(
                    f"{key}: budget_overrides names role {role!r} with no "
                    f"role-packs/{role}/policy.yaml"
                )
                continue
            for field, value in (fields or {}).items():
                default = defaults.get(field)
                if default is None:
                    violations.append(
                        f"{key}: budget_overrides.{role}.{field} has no "
                        f"matching `budgets.{field}` in role-packs/{role}/policy.yaml"
                    )
                    continue
                if value > default:
                    violations.append(
                        f"{key}: budget_overrides.{role}.{field} is {value}, "
                        f"which is greater than role-packs/{role}/policy.yaml's "
                        f"own default {default} — overrides may only tighten"
                    )
    return violations


def validate_no_duplicate_projects(products: dict) -> list[str]:
    violations = []
    seen: dict[tuple, str] = {}
    for key, entry in products.items():
        project = (entry or {}).get("project") or {}
        pid = (project.get("owner"), project.get("number"))
        if pid in seen:
            violations.append(
                f"{key} and {seen[pid]} share the same project "
                f"{{owner: {pid[0]!r}, number: {pid[1]!r}}} — independent "
                f"products do not share a board"
            )
        else:
            seen[pid] = key
    return violations


def validate_structure(products: dict, ladder_environments: dict, role_pack_names: set,
                        role_pack_budgets: dict) -> list[str]:
    violations = []
    violations += validate_environments_known(products, set(ladder_environments))
    violations += validate_environments_not_weakened(products, ladder_environments)
    violations += validate_roles_have_packs(products, role_pack_names)
    violations += validate_budget_overrides(products, role_pack_budgets)
    violations += validate_no_duplicate_projects(products)
    return violations


# --------------------------------------------------------------------------
# Platform — the policy's claims checked against what the API returns.
# Each rule takes the fetchers as arguments so tests never call `gh`.
# --------------------------------------------------------------------------

def validate_repo_resolves(products: dict, fetch_repo: Callable[[str], dict | None]) -> list[str]:
    violations = []
    for key, entry in products.items():
        repo = (entry or {}).get("repo")
        info = fetch_repo(repo)
        if info is None:
            violations.append(
                f"{key}: repo {repo!r} does not resolve (GET /repos/{repo} failed)"
            )
            continue
        full_name = info.get("full_name", "")
        if full_name.lower() != str(repo).lower():
            violations.append(
                f"{key}: repo {repo!r} resolves to {full_name!r} instead — "
                f"a rename or redirect means this entry's `repo` is stale"
            )
    return violations


def validate_project_resolves(products: dict, fetch_project: Callable[[str, int], dict | None]) -> list[str]:
    violations = []
    for key, entry in products.items():
        project = (entry or {}).get("project") or {}
        owner, number = project.get("owner"), project.get("number")
        if fetch_project(owner, number) is None:
            violations.append(
                f"{key}: project {{owner: {owner!r}, number: {number!r}}} "
                f"does not resolve (neither a user nor an organization "
                f"project board)"
            )
    return violations


def validate_bootstrapped(
    products: dict,
    fetch_repo: Callable[[str], dict | None],
    fetch_exists: Callable[[str, str], bool],
    fetch_protection: Callable[[str, str], dict | None],
) -> list[str]:
    violations = []
    for key, entry in products.items():
        entry = entry or {}
        if not entry.get("bootstrapped"):
            continue
        repo = entry.get("repo")
        info = fetch_repo(repo)
        if info is None:
            violations.append(
                f"{key}: bootstrapped: true but repo {repo!r} does not "
                f"resolve, so nothing about it can be verified"
            )
            continue

        missing = []
        if not fetch_exists(repo, "CONVENTIONS.md"):
            missing.append("CONVENTIONS.md")
        if not fetch_exists(repo, ".github/CODEOWNERS"):
            missing.append(".github/CODEOWNERS")
        if not (
            fetch_exists(repo, ".github/pull_request_template.md")
            or fetch_exists(repo, "PULL_REQUEST_TEMPLATE.md")
            or fetch_exists(repo, ".github/PULL_REQUEST_TEMPLATE")
        ):
            missing.append("a pull request template")

        default_branch = info.get("default_branch")
        context = entry.get("dod_check_context", DEFAULT_DOD_CONTEXT)
        protection = fetch_protection(repo, default_branch) if default_branch else None
        contexts = ((protection or {}).get("required_status_checks") or {}).get("contexts") or []
        if context not in contexts:
            missing.append(
                f"required status check {context!r} on the default branch "
                f"({default_branch!r})"
            )

        if missing:
            violations.append(
                f"{key}: bootstrapped: true but not verified — missing: "
                f"{', '.join(missing)}"
            )
    return violations


# --------------------------------------------------------------------------
# The world — gh api, isolated so tests never call it.
# --------------------------------------------------------------------------

def gh(args: list[str]) -> str:
    return subprocess.run(
        ["gh", *args], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout


_PROJECT_QUERY = """
query($login: String!, $number: Int!) {
  user(login: $login) { projectV2(number: $number) { id } }
  organization(login: $login) { projectV2(number: $number) { id } }
}
"""


def fetch_repo(repo: str) -> dict | None:
    try:
        raw = gh(["api", f"repos/{repo}"])
    except subprocess.CalledProcessError:
        return None
    return json.loads(raw)


def fetch_project(owner: str, number: int) -> dict | None:
    try:
        raw = gh([
            "api", "graphql",
            "-f", f"query={_PROJECT_QUERY}",
            "-f", f"login={owner}",
            "-F", f"number={number}",
        ])
    except subprocess.CalledProcessError:
        return None
    data = json.loads(raw).get("data") or {}
    user_project = (data.get("user") or {}).get("projectV2")
    if user_project:
        return user_project
    return (data.get("organization") or {}).get("projectV2")


def fetch_exists(repo: str, path: str) -> bool:
    try:
        gh(["api", f"repos/{repo}/contents/{path}"])
        return True
    except subprocess.CalledProcessError:
        return False


def fetch_protection(repo: str, branch: str) -> dict | None:
    try:
        raw = gh(["api", f"repos/{repo}/branches/{branch}/protection"])
    except subprocess.CalledProcessError:
        return None
    return json.loads(raw)


def role_pack_names(role_packs_dir: Path) -> set:
    if not role_packs_dir.is_dir():
        return set()
    return {
        p.name for p in role_packs_dir.iterdir()
        if p.is_dir() and (p / "policy.yaml").is_file()
    }


def load_role_pack_budgets(role_packs_dir: Path, names: set) -> dict:
    out = {}
    for name in names:
        policy = load_yaml(role_packs_dir / name / "policy.yaml")
        out[name] = policy.get("budgets") or {}
    return out


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(
    argv: list[str] | None = None,
    *,
    fetch_repo: Callable[[str], dict | None] = fetch_repo,
    fetch_project: Callable[[str, int], dict | None] = fetch_project,
    fetch_exists: Callable[[str, str], bool] = fetch_exists,
    fetch_protection: Callable[[str, str], dict | None] = fetch_protection,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--policy", type=Path, default=PRODUCTS_POLICY,
                        help="path to the product registry (default: policies/products.yaml)")
    parser.add_argument("--environments-policy", type=Path, default=ENV_POLICY,
                        help="path to the ladder policy (default: policies/environments.yaml)")
    parser.add_argument("--role-packs-dir", type=Path, default=ROLE_PACKS_DIR,
                        help="path to role-packs/ (default: role-packs)")
    args = parser.parse_args(argv)

    policy = load_yaml(args.policy)
    products = policy.get("products") or {}
    if not products:
        print("FAIL: policy declares no `products`", file=sys.stderr)
        return 1

    env_policy = load_yaml(args.environments_policy)
    ladder_environments = env_policy.get("environments") or {}

    names = role_pack_names(args.role_packs_dir)
    budgets = load_role_pack_budgets(args.role_packs_dir, names)

    violations = validate_structure(products, ladder_environments, names, budgets)
    if violations:
        for v in violations:
            print(f"FAIL: {v}", file=sys.stderr)
        print(f"\n{len(violations)} violation(s) in {args.policy}", file=sys.stderr)
        return 1

    violations = []
    violations += validate_repo_resolves(products, fetch_repo)
    violations += validate_project_resolves(products, fetch_project)
    violations += validate_bootstrapped(products, fetch_repo, fetch_exists, fetch_protection)
    if violations:
        for v in violations:
            print(f"FAIL: {v}", file=sys.stderr)
        print(f"\n{len(violations)} violation(s) against the live platform", file=sys.stderr)
        return 1

    print(f"OK: every product in {args.policy} is valid and matches the live platform")
    return 0


if __name__ == "__main__":
    sys.exit(main())
