#!/usr/bin/env python3
"""Install, or verify, the governance floor a product repo needs (PRD §14).

`policies/products.yaml` can claim `bootstrapped: true` for a product; this
is the thing that makes the claim true, and the thing that checks it against
the live repo instead of trusting the flag. Per that policy's own
`bootstrapped_is_verified` rule, four things must hold on the *target*
repo, not on this file's say-so:

  1. `CONVENTIONS.md` at the repo root
  2. `.github/CODEOWNERS`
  3. a PR template (`.github/pull_request_template.md`, or either of the
     two other locations GitHub itself recognizes)
  4. branch protection on the default branch: a required status check
     (`dod` by default — see `--dod-context`), enforced against admins too
     — the combination this repo's own `main` uses to make a direct push
     structurally impossible rather than merely forbidden

    bootstrap-product.py --check <product>      # report state, change nothing
    bootstrap-product.py --install <product>     # install what's missing

Both modes read the target `repo` from `policies/products.yaml`; a name
not declared there is refused rather than guessed at.

`--check` is the load-bearing mode. Installing is a one-time convenience;
verifying is what stops the registry lying after the fact — a DoD check
someone later removed from branch protection is exactly the state a
`bootstrapped: true` entry must not be allowed to paper over.

`--install` is conservative on purpose:
  - a file that already exists with the exact content this script would
    write is left alone (idempotent — the second run is a no-op);
  - a file that exists with *different* content is reported and left
    untouched — products may have their own conventions, and silently
    replacing them is the kind of thing that makes a tool untrustworthy;
  - branch protection needs admin on the target repo. A credential without
    it gets files installed and an explicit "protection not applied,
    missing admin" — never a quiet partial success.
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable, NamedTuple, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
PRODUCTS_POLICY = REPO_ROOT / "policies" / "products.yaml"
DEFAULT_DOD_CONTEXT = "dod"

CANONICAL_PR_TEMPLATE = ".github/pull_request_template.md"
PR_TEMPLATE_VARIANTS = (
    CANONICAL_PR_TEMPLATE,
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/PULL_REQUEST_TEMPLATE",  # a directory; existence is enough
)


# --------------------------------------------------------------------------
# Desired content — pure functions of the target repo's slug.
# --------------------------------------------------------------------------

def conventions_md() -> str:
    return """# Conventions

These rules are enforced by the DoD check, a required status check on
the default branch.

## Branches

`story/FDY-<issue#>-<slug>` — bugs use `bug/FDY-<issue#>-<slug>`.

## Commit trailers

Every commit on a PR branch carries four trailers:

```
Work-Item: <owner>/<repo>#<issue>
Requirement: REQ-0XX            # comma-separated list allowed
Agent-Role: <orchestrator|pm|architect|developer|qa|devops|techwriter|human>
Harness: <claude-code/x.y|codex/x.y|manual|...>
```

Pre-automation commits use `Agent-Role: human` and `Harness: manual`.
That is honest provenance, not a gap.

## Definition of Done

The policy of record lives in the control plane's `policies/dod.yaml`.
The enforced subset runs here as the `dod` required status check on the
default branch. If the policy and the check disagree, the policy wins.
"""


def codeowners(owner: str) -> str:
    return f"""# Review routing. Inert until required reviews route to more than one
# identity. Kept versioned from day one rather than added later.
* @{owner}
"""


def pull_request_template() -> str:
    return """## What

<!-- the change, in plain words -->

## Work item

Closes #

## Requirement(s)

REQ-

## Definition of Done

- [ ] Every commit carries the four trailers (Work-Item, Requirement, Agent-Role, Harness)
- [ ] Work item linked above
- [ ] Acceptance criteria on the issue are met (say how in Evidence)

## Evidence

<!-- test output, screenshots, links, or the reason none is needed -->
"""


FILE_ITEMS: tuple[tuple[str, str, Callable[[str], str]], ...] = (
    ("CONVENTIONS.md", "CONVENTIONS.md", lambda repo: conventions_md()),
    (".github/CODEOWNERS", ".github/CODEOWNERS", lambda repo: codeowners(repo.split("/")[0])),
    ("PR template", CANONICAL_PR_TEMPLATE, lambda repo: pull_request_template()),
)


# --------------------------------------------------------------------------
# Planning — pure. Current state in, a verdict and (for install) whether to
# write, out. No API call, no filesystem, so this is what the tests exercise.
# --------------------------------------------------------------------------

class ItemResult(NamedTuple):
    name: str
    status: str      # present | missing | created | unchanged | conflict |
                      # present_elsewhere | no_admin
    detail: str


def check_file(name: str, existing: Optional[str]) -> ItemResult:
    if existing is None:
        return ItemResult(name, "missing", f"not found at HEAD")
    return ItemResult(name, "present", "found at HEAD")


def check_pr_template(existing_by_path: dict[str, Optional[str]]) -> ItemResult:
    for path in PR_TEMPLATE_VARIANTS:
        if existing_by_path.get(path) is not None:
            return ItemResult("PR template", "present", f"found at {path}")
    return ItemResult("PR template", "missing", "not found at any of " + ", ".join(PR_TEMPLATE_VARIANTS))


def check_branch_protection(protection: Optional[dict], context: str) -> ItemResult:
    """A required status check, enforced against admins too.

    That second part is what actually makes direct pushes structurally
    impossible rather than merely forbidden (this repo's own developer
    charter's words): GitHub applies `required_status_checks` to direct
    pushes as well as PR merges, but only for non-admins unless
    `enforce_admins` is also on. `required_pull_request_reviews` is a
    separate, optional review-count gate this repo's own `main` does not
    set — checking for it here would fail this bootstrapper against the
    exact reference configuration the work item points to.
    """
    if protection is None:
        return ItemResult("branch protection", "missing", "no protection configured on the default branch")
    contexts = ((protection.get("required_status_checks") or {}).get("contexts") or [])
    has_check = context in contexts
    enforce_admins = protection.get("enforce_admins")
    admins_enforced = bool(enforce_admins.get("enabled")) if isinstance(enforce_admins, dict) else bool(enforce_admins)
    if has_check and admins_enforced:
        return ItemResult(
            "branch protection", "present",
            f"required status check {context!r} present; enforced against admins, so direct pushes are structurally blocked",
        )
    missing = []
    if not has_check:
        missing.append(f"required status check {context!r} (has {contexts!r})")
    if not admins_enforced:
        missing.append("enforce_admins (admins — and only admins can push directly — are exempt from the check)")
    return ItemResult("branch protection", "missing", "; ".join(missing))


def plan_file_install(name: str, existing: Optional[str], desired: str) -> ItemResult:
    if existing is None:
        return ItemResult(name, "created", "did not exist, will be written")
    if existing == desired:
        return ItemResult(name, "unchanged", "already installed, identical content")
    return ItemResult(name, "conflict", "exists with different content — left untouched")


def plan_pr_template_install(existing_by_path: dict[str, Optional[str]], desired: str) -> ItemResult:
    canonical = existing_by_path.get(CANONICAL_PR_TEMPLATE)
    if canonical is not None:
        if canonical == desired:
            return ItemResult("PR template", "unchanged", f"already installed at {CANONICAL_PR_TEMPLATE}")
        return ItemResult("PR template", "conflict", f"{CANONICAL_PR_TEMPLATE} exists with different content — left untouched")
    for path in PR_TEMPLATE_VARIANTS:
        if path == CANONICAL_PR_TEMPLATE:
            continue
        if existing_by_path.get(path) is not None:
            return ItemResult("PR template", "present_elsewhere", f"already present at {path} — leaving it, not adding a second template")
    return ItemResult("PR template", "created", f"did not exist, will be written to {CANONICAL_PR_TEMPLATE}")


def plan_branch_protection(protection: Optional[dict], context: str, is_admin: bool) -> ItemResult:
    current = check_branch_protection(protection, context)
    if current.status == "present":
        return ItemResult("branch protection", "unchanged", current.detail)
    if not is_admin:
        return ItemResult(
            "branch protection", "no_admin",
            f"missing ({current.detail}) but the credential lacks admin on this repo — "
            "protection was NOT configured; files were installed regardless",
        )
    return ItemResult("branch protection", "created", f"was missing ({current.detail}), now configured")


OK_STATUSES = {"present", "unchanged", "created", "present_elsewhere"}


def is_ok(results: list[ItemResult]) -> bool:
    return all(r.status in OK_STATUSES for r in results)


# --------------------------------------------------------------------------
# The registry — pure, offline.
# --------------------------------------------------------------------------

def load_products(path: Path) -> dict:
    try:
        import yaml
    except ImportError:  # pragma: no cover
        sys.exit("bootstrap-product: PyYAML is required")
    if not path.is_file():
        sys.exit(f"bootstrap-product: {path} not found — the product registry is the policy")
    return (yaml.safe_load(path.read_text()) or {}).get("products", {}) or {}


def resolve_repo(products: dict, name: str) -> str:
    if name not in products:
        sys.exit(
            f"bootstrap-product: {name!r} is not declared in policies/products.yaml — refusing "
            "(a product not in the registry has no repo to trust)"
        )
    repo = (products[name] or {}).get("repo")
    if not repo:
        sys.exit(f"bootstrap-product: {name!r} has no `repo` in policies/products.yaml")
    return repo


# --------------------------------------------------------------------------
# The world — gh api, isolated so tests never call it.
# --------------------------------------------------------------------------

def gh(args: list[str], stdin: Optional[str] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gh", *args], cwd=REPO_ROOT, input=stdin, capture_output=True, text=True
    )


def api_get_file(repo: str, path: str) -> Optional[str]:
    """Decoded file content at `path` on `repo`'s default branch, or None."""
    proc = gh(["api", f"repos/{repo}/contents/{path}"])
    if proc.returncode != 0:
        if "404" in proc.stderr or "Not Found" in proc.stderr:
            return None
        raise RuntimeError(f"GET {path} on {repo} failed: {proc.stderr.strip()}")
    data = json.loads(proc.stdout)
    if isinstance(data, list):
        return ""  # a directory exists (e.g. PULL_REQUEST_TEMPLATE/) — presence, not content
    return base64.b64decode(data["content"]).decode()


def api_put_file(repo: str, path: str, content: str, message: str) -> None:
    args = [
        "api", "-X", "PUT", f"repos/{repo}/contents/{path}",
        "-f", f"message={message}",
        "-f", f"content={base64.b64encode(content.encode()).decode()}",
    ]
    proc = gh(args)
    if proc.returncode != 0:
        raise RuntimeError(f"PUT {path} on {repo} failed: {proc.stderr.strip()}")


def api_repo_meta(repo: str) -> dict:
    proc = gh(["api", f"repos/{repo}"])
    if proc.returncode != 0:
        raise RuntimeError(f"GET {repo} failed: {proc.stderr.strip()}")
    data = json.loads(proc.stdout)
    return {
        "default_branch": data["default_branch"],
        "is_admin": bool((data.get("permissions") or {}).get("admin")),
    }


def api_get_protection(repo: str, branch: str) -> Optional[dict]:
    proc = gh(["api", f"repos/{repo}/branches/{branch}/protection"])
    if proc.returncode != 0:
        if "404" in proc.stderr or "Not Found" in proc.stderr or "Branch not protected" in proc.stderr:
            return None
        raise RuntimeError(f"GET protection on {repo}/{branch} failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def api_put_protection(repo: str, branch: str, context: str) -> None:
    # Matches this repo's own `main`: required_status_checks + enforce_admins
    # is what blocks a direct push (see check_branch_protection's docstring).
    # required_pull_request_reviews is left null, same as the reference.
    body = {
        "required_status_checks": {"strict": False, "contexts": [context]},
        "enforce_admins": True,
        "required_pull_request_reviews": None,
        "restrictions": None,
    }
    proc = gh(["api", "-X", "PUT", f"repos/{repo}/branches/{branch}/protection", "--input", "-"], stdin=json.dumps(body))
    if proc.returncode != 0:
        raise RuntimeError(f"PUT protection on {repo}/{branch} failed: {proc.stderr.strip()}")


# --------------------------------------------------------------------------
# Orchestration — wires planning to the world (or, in tests, to fakes).
# --------------------------------------------------------------------------

def do_check(
    repo: str,
    dod_context: str,
    *,
    get_file: Callable[[str, str], Optional[str]] = api_get_file,
    get_protection: Callable[[str, str], Optional[dict]] = api_get_protection,
    get_repo_meta: Callable[[str], dict] = api_repo_meta,
) -> list[ItemResult]:
    results = []
    for name, path, _ in FILE_ITEMS:
        if path == CANONICAL_PR_TEMPLATE:
            existing = {p: get_file(repo, p) for p in PR_TEMPLATE_VARIANTS}
            results.append(check_pr_template(existing))
        else:
            results.append(check_file(name, get_file(repo, path)))
    meta = get_repo_meta(repo)
    protection = get_protection(repo, meta["default_branch"])
    results.append(check_branch_protection(protection, dod_context))
    return results


def do_install(
    repo: str,
    dod_context: str,
    *,
    get_file: Callable[[str, str], Optional[str]] = api_get_file,
    put_file: Callable[[str, str, str, str], None] = api_put_file,
    get_protection: Callable[[str, str], Optional[dict]] = api_get_protection,
    put_protection: Callable[[str, str, str], None] = api_put_protection,
    get_repo_meta: Callable[[str], dict] = api_repo_meta,
) -> list[ItemResult]:
    results = []
    for name, path, content_fn in FILE_ITEMS:
        desired = content_fn(repo)
        if path == CANONICAL_PR_TEMPLATE:
            existing = {p: get_file(repo, p) for p in PR_TEMPLATE_VARIANTS}
            plan = plan_pr_template_install(existing, desired)
        else:
            plan = plan_file_install(name, get_file(repo, path), desired)
        if plan.status == "created":
            put_file(repo, path, desired, f"bootstrap-product: install {name}")
        results.append(plan)

    meta = get_repo_meta(repo)
    protection = get_protection(repo, meta["default_branch"])
    plan = plan_branch_protection(protection, dod_context, meta["is_admin"])
    if plan.status == "created":
        put_protection(repo, meta["default_branch"], dod_context)
    results.append(plan)
    return results


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None, **world: Callable) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", metavar="PRODUCT", help="report state against policies/products.yaml, change nothing")
    mode.add_argument("--install", metavar="PRODUCT", help="install what is missing (never overwrites a differing file)")
    parser.add_argument("--products-file", type=Path, default=PRODUCTS_POLICY,
                         help="path to the product registry (default: policies/products.yaml)")
    parser.add_argument("--dod-context", default=DEFAULT_DOD_CONTEXT,
                         help=f"required status check context name this product's DoD check reports as (default: {DEFAULT_DOD_CONTEXT!r})")
    args = parser.parse_args(argv)

    product = args.check or args.install
    products = load_products(args.products_file)
    repo = resolve_repo(products, product)

    if args.check:
        results = do_check(repo, args.dod_context, **{k: v for k, v in world.items() if k in
                            ("get_file", "get_protection", "get_repo_meta")})
    else:
        results = do_install(repo, args.dod_context, **{k: v for k, v in world.items() if k in
                             ("get_file", "put_file", "get_protection", "put_protection", "get_repo_meta")})

    mode_label = "check" if args.check else "install"
    print(f"bootstrap-product --{mode_label} {product} ({repo})")
    for r in results:
        print(f"  {r.status.upper():17s} {r.name} — {r.detail}")

    ok = is_ok(results)
    print(f"\n{'OK' if ok else 'INCOMPLETE'}: {sum(1 for r in results if r.status in OK_STATUSES)}/{len(results)} item(s) satisfied")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
