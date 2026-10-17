#!/usr/bin/env python3
"""From an empty repo to a first dispatched story in one command (#323).

    foundry-init.py owner/product                 # print the plan, ask, apply
    foundry-init.py owner/product --plan          # print the plan, change nothing
    foundry-init.py owner/product --yes           # apply without asking
    foundry-init.py owner/product --create-app    # also create the Foundry GitHub App
    foundry-init.py owner/product --key my-key    # registry key (default: the repo name)

Run it from a checkout of the control plane, as its owner (`gh auth login`).
It never creates a repository, and never installs the App for you:
installing an App on a repo is the owner's click, by design.

Every run reads first and prints the whole plan before changing anything,
so a second run against a finished product plans nothing. Like
`bootstrap-product.py`, which it reuses for the governance files, it never
overwrites a file that exists with different content. A product's own
CONVENTIONS.md or CI stays the product's.

What it sets up, in order:

  control plane  - the LLM credential and the Foundry GitHub App (ADR-0011;
                   `--create-app` runs the manifest flow)
                 - every label in policies/labels.yaml, plus `product:<key>`
  product        - CONVENTIONS.md, CODEOWNERS, PR template, the `dod` check
                   (bootstrap-product.py's floor)
                 - the `scope` check, CI, Dependabot, `FOUNDRY_CONTROL_PLANE`
                 - environments (preview -> dev -> staging -> prod, prod
                   behind a human reviewer)
                 - vulnerability alerts, CodeQL default setup
                 - branch protection requiring `dod` and `scope`
  board          - a Projects v2 board copied from the control plane's,
                   linked to the product
  tracker        - an "interview me about this product" issue for the PM
                 - the policies/products.yaml entry, as a pull request
  once merged    - a rerun marks the interview `status:ready` and
                   dispatches it: the first dispatched story

Then it scores readiness: can an agent build and test this unattended?
"""

from __future__ import annotations

import argparse
import base64
import http.server
import importlib.util
import json
import os
import secrets as pysecrets
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import foundry_config  # noqa: E402  (#324)

LABELS_PATH = REPO_ROOT / "policies" / "labels.yaml"
PRODUCTS_PATH = REPO_ROOT / "policies" / "products.yaml"
ENVIRONMENTS_PATH = REPO_ROOT / "policies" / "environments.yaml"
MANIFEST_PATH = REPO_ROOT / "infra" / "github-app" / "manifest.json"
SCOPE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "scope-check.yml"

_spec = importlib.util.spec_from_file_location("bootstrap_product", REPO_ROOT / "scripts" / "bootstrap-product.py")
bootstrap = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("bootstrap_product", bootstrap)
_spec.loader.exec_module(bootstrap)

REQUIRED_CHECKS = ("dod", "scope")
LLM_SECRETS = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")
APP_VAR, APP_SECRET, APP_SLUG_VAR = "FOUNDRY_APP_CLIENT_ID", "FOUNDRY_APP_PRIVATE_KEY", "FOUNDRY_APP_SLUG"
INTERVIEW_TITLE = "Interview me about {key}"
REGISTRY_BRANCH = "foundry-init/{key}"
MANIFEST_PORT = 8765
# What GitHub answers when the account's plan cannot protect a private
# repo's branch or put a required reviewer on its environment.
PLAN_LIMITED = ("Upgrade to GitHub Pro", "billing plan supports")
PLAN_FIX = ("GitHub Free cannot do this on a private repo: make it public "
            "(`gh repo edit {repo} --visibility public --accept-visibility-change-consequences`) "
            "or move to GitHub Pro/Team")


# --------------------------------------------------------------------------
# What gets installed into a product. Plain text, so the plan can say
# exactly what it will write.
# --------------------------------------------------------------------------

CI_WORKFLOW = """\
# Installed by foundry-init (#323). It finds the product's build and runs its
# tests, so an agent's PR has a red or green to answer to from day one.
# Replace it with the product's own pipeline once there is one; foundry-init
# never overwrites a file that differs from this.
name: CI

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  test:
    name: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Detect the build and run its tests
        run: |
          set -euo pipefail
          if [ -f package.json ]; then
            npm ci || npm install
            npm test
          elif [ -f pyproject.toml ] || [ -f requirements.txt ]; then
            python3 -m pip install --quiet pytest
            if [ -f requirements.txt ]; then python3 -m pip install --quiet -r requirements.txt; fi
            if [ -f pyproject.toml ]; then python3 -m pip install --quiet -e .; fi
            python3 -m pytest
          elif [ -f go.mod ]; then
            go test ./...
          elif [ -f Cargo.toml ]; then
            cargo test
          elif [ -f Makefile ] && grep -q '^test:' Makefile; then
            make test
          else
            echo "::notice::No build found yet (package.json, pyproject.toml, requirements.txt, go.mod, Cargo.toml or a Makefile test target). The first story should add one."
          fi
"""

DEPENDABOT_BASE = """\
# Installed by foundry-init (#323).
version: 2
updates:
  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: weekly
"""

ECOSYSTEMS = (("package.json", "npm"), ("requirements.txt", "pip"), ("pyproject.toml", "pip"),
              ("go.mod", "gomod"), ("Cargo.toml", "cargo"))
BUILD_MANIFESTS = ("package.json", "pyproject.toml", "requirements.txt", "go.mod", "Cargo.toml", "Makefile")
TEST_DIRS = ("tests", "test", "__tests__", "spec")


def dependabot_config(root_files: set[str]) -> str:
    text, seen = DEPENDABOT_BASE, set()
    for manifest, ecosystem in ECOSYSTEMS:
        if manifest in root_files and ecosystem not in seen:
            seen.add(ecosystem)
            text += (f"  - package-ecosystem: {ecosystem}\n    directory: /\n"
                     f"    schedule:\n      interval: weekly\n")
    return text


def registry_entry(key: str, repo: str, project: Optional[dict], environments: list[dict],
                   bootstrapped: bool, today: str) -> str:
    """The products.yaml entry, as text to append under `products:`, which
    is the file's last key. Appended rather than re-dumped so every comment
    in the registry survives.
    """
    proj = (f"{{owner: {project['owner']}, number: {project['number']}}}" if project
            else "{owner: " + repo.split("/")[0] + ", number: 0}")
    envs = "".join(f"      - {{name: {e['name']}, human_reviewer_required: "
                   f"{str(bool(e['human_reviewer_required'])).lower()}}}\n" for e in environments)
    return (
        f"\n  {key}:\n"
        f"    repo: {repo}\n"
        f"    project: {proj}\n"
        f"    environments:\n{envs}"
        f"    roles: [product-manager, architect, developer, qa, devops, techwriter, security]\n"
        f"    # ADR-0011: products lay out differently from the control plane. A\n"
        f"    # developer may write root-level files (package.json, README.md, ...)\n"
        f"    # here; a pack's own deny list still wins, so .github/ stays devops's.\n"
        f"    write_scope_extra:\n"
        f"      developer: [\"*\"]\n"
        f"    bootstrapped: {str(bootstrapped).lower()}\n"
        f"    notes: >-\n"
        f"      Registered by scripts/foundry-init.py on {today}. `bootstrapped` was\n"
        f"      {'verified' if bootstrapped else 'NOT verified'} by bootstrap-product.py's floor at that time.\n"
    )


def interview_body(key: str, repo: str) -> str:
    return f"""\
Product `{key}` (`{repo}`) is set up and has no requirements yet. Interview its owner and turn the answers into the first stories.

Ask in one `## Questions` comment:
- at most 5 questions;
- each with options, a recommended answer, and why it matters;
- covering who the product is for, the first thing it must do, what "done" looks like for that, constraints (stack, hosting, data, budget), and what is out of scope.

Stop until the owner answers. Then write:
- `prds/` and `requirements/` entries in the product repo;
- the first stories as work items labelled `product:{key}`, each with acceptance criteria, ready for refinement.

The very first story should scaffold the build and a test, so that CI has something to run.

→ **REQ-008, REQ-004**

## Acceptance criteria
- [ ] The owner's answers are recorded on this issue.
- [ ] The product has a PRD and requirement IDs that trace to those answers.
- [ ] At least one story labelled `product:{key}` exists with acceptance criteria, and its first story scaffolds the build and a test.
"""


# --------------------------------------------------------------------------
# The plan. Reads the world only through `w`, so the tests run it against a
# fake GitHub. A step carries the closure that applies it, so printing the
# plan and applying it can never disagree.
# --------------------------------------------------------------------------

@dataclass
class Step:
    where: str
    title: str
    status: str            # ok | todo | waiting | manual | blocked | unverified
    detail: str
    apply: Optional[Callable[[], str]] = None


@dataclass
class Ctx:
    control_plane: str
    repo: str
    key: str
    login: str
    create_app: bool = False
    today: str = field(default_factory=lambda: time.strftime("%Y-%m-%d"))
    # Filled while applying, read by later steps.
    project: Optional[dict] = None
    interview: Optional[int] = None
    app: Optional[dict] = None


def load_yaml(path: Path) -> dict:
    import yaml
    return yaml.safe_load(path.read_text()) or {}


def desired_labels(key: str, policy: dict) -> list[dict]:
    pl = policy["product_label"]
    return list(policy["labels"]) + [{"name": f"{pl['prefix']}{key}", "color": pl["color"],
                                      "description": pl["description"].format(key=key)}]


def desired_environments(product_entry: Optional[dict], ladder: dict) -> list[dict]:
    """The product's own ladder if registered, else the registry template's,
    which is the full preview -> dev -> staging -> prod ladder."""
    envs = (product_entry or {}).get("environments")
    if envs:
        return envs
    return [{"name": n, "human_reviewer_required": bool((ladder["environments"][n] or {}).get("human_reviewer_required"))}
            for n in ladder["promotion_order"]]


def product_files(w, ctx: Ctx, root_files: set[str]) -> list[tuple[str, str, str]]:
    files = [(name, path, fn(ctx.repo)) for name, path, fn in bootstrap.FILE_ITEMS]
    files += [
        ("scope check workflow", ".github/workflows/scope-check.yml", SCOPE_WORKFLOW.read_text()),
        ("CI workflow", ".github/workflows/ci.yml", CI_WORKFLOW),
        ("Dependabot config", ".github/dependabot.yml", dependabot_config(root_files)),
    ]
    return files


def plan(w, ctx: Ctx) -> list[Step]:
    cp, repo, key = ctx.control_plane, ctx.repo, ctx.key
    steps: list[Step] = []

    meta = w.repo(repo)
    if meta is None:
        return [Step(repo, "product repo exists", "blocked",
                     f"`{repo}` not found. Create it first (foundry-init never creates repos): "
                     f"`gh repo create {repo} --private`")]
    if not meta["admin"]:
        return [Step(repo, "admin on the product repo", "blocked",
                     f"`{ctx.login}` is not an admin of `{repo}`; protection and environments need admin")]
    cp_meta = w.repo(cp)
    if cp_meta is None or not cp_meta["admin"]:
        return [Step(cp, "admin on the control plane", "blocked",
                     f"`{ctx.login}` needs admin on `{cp}` to set its labels, variables and secrets")]

    # --- control plane: credentials -----------------------------------
    secrets = w.secret_names(cp)
    llm = [s for s in LLM_SECRETS if s in secrets]
    steps.append(Step(cp, "LLM credential", "ok" if llm else "manual",
                      f"`{llm[0]}` is set" if llm else
                      "set one: `claude setup-token | gh secret set CLAUDE_CODE_OAUTH_TOKEN "
                      f"--repo {cp}` or `gh secret set ANTHROPIC_API_KEY --repo {cp}`"))

    client_id = w.variable(cp, APP_VAR)
    if client_id and APP_SECRET in secrets:
        slug = w.variable(cp, APP_SLUG_VAR)
        steps.append(Step(cp, "Foundry GitHub App", "ok", f"`{APP_VAR}` and `{APP_SECRET}` are set"
                          + (f" (`{slug}[bot]`)" if slug else "")))
        installed = w.app_installed(ctx, repo)
        url = f"https://github.com/apps/{slug}/installations/new" if slug else "the App's settings page"
        if installed is None:
            steps.append(Step(repo, "App installed on the product", "unverified",
                              f"a user token cannot read installations; confirm `{repo}` is selected at {url}"))
        else:
            steps.append(Step(repo, "App installed on the product", "ok" if installed else "manual",
                              "installed" if installed else f"install it on `{repo}`: {url}"))
    elif ctx.create_app:
        steps.append(Step(cp, "Foundry GitHub App", "todo",
                          f"create `foundry-{cp.split('/')[0].lower()}` from infra/github-app/manifest.json "
                          "(one click in the browser), store its client ID and key, open its install page",
                          lambda: w.create_app(ctx)))
    else:
        steps.append(Step(cp, "Foundry GitHub App", "manual",
                          f"not configured (`{APP_VAR}` / `{APP_SECRET}`); rerun with --create-app"))

    # --- control plane: labels ------------------------------------------
    want = desired_labels(key, load_yaml(LABELS_PATH))
    have = w.label_names(cp)
    missing = [l for l in want if l["name"] not in have]
    def make_labels():
        for l in missing:
            w.create_label(cp, l["name"], l["color"], l["description"])
        return f"created {len(missing)} label(s)"
    steps.append(Step(cp, "labels", "todo" if missing else "ok",
                      (f"create {len(missing)}: " + ", ".join(l["name"] for l in missing)) if missing
                      else f"all {len(want)} present", make_labels if missing else None))

    # --- product: files -----------------------------------------------
    root = w.root_files(repo)
    for name, path, desired in product_files(w, ctx, root):
        existing = w.get_file(repo, path)
        if path == bootstrap.CANONICAL_PR_TEMPLATE and existing is None:
            if any(w.get_file(repo, p) is not None for p in bootstrap.PR_TEMPLATE_VARIANTS[1:]):
                steps.append(Step(repo, name, "ok", "present at another location GitHub recognises"))
                continue
        if existing is None:
            steps.append(Step(repo, name, "todo", f"write `{path}`",
                              lambda p=path, d=desired, n=name: (
                                  w.put_file(repo, p, d, f"foundry-init: install {n}"), f"wrote {p}")[1]))
        else:
            same = existing == desired
            steps.append(Step(repo, name, "ok", "present" + ("" if same else " (differs from the template; left as it is)")))

    if w.variable(repo, "FOUNDRY_CONTROL_PLANE") == cp:
        steps.append(Step(repo, "FOUNDRY_CONTROL_PLANE variable", "ok", f"= {cp}"))
    else:
        steps.append(Step(repo, "FOUNDRY_CONTROL_PLANE variable", "todo",
                          f"set to `{cp}` so the scope check reads the packs from there",
                          lambda: (w.set_variable(repo, "FOUNDRY_CONTROL_PLANE", cp), "set")[1]))

    protection = None if meta["empty"] else w.protection(repo, meta["default_branch"])
    limited = bool((protection or {}).get("unavailable"))

    # --- product: environments ----------------------------------------
    products = w.registry(cp)
    entry = (products.get("products") or {}).get(key)
    envs = desired_environments(entry, load_yaml(ENVIRONMENTS_PATH))
    have_envs = w.environments(repo)
    # On a plan that cannot add a required reviewer, a reviewer-less
    # environment is as far as this can go; the gap is reported, not retried.
    todo_envs = [e for e in envs if e["name"] not in have_envs
                 or (e["human_reviewer_required"] and not have_envs[e["name"]] and not limited)]
    unreviewed = [e["name"] for e in envs if e["human_reviewer_required"] and e["name"] in have_envs
                  and not have_envs[e["name"]] and limited]

    def make_environments():
        notes = []
        for e in todo_envs:
            notes.append(w.put_environment(repo, e["name"],
                                           [ctx.login] if e["human_reviewer_required"] else []))
        return f"configured {len(todo_envs)}" + "".join(f"; {n}" for n in notes if n)
    if unreviewed and not todo_envs:
        steps.append(Step(repo, "environments", "manual",
                          f"{', '.join(unreviewed)} has no required reviewer. " + PLAN_FIX.format(repo=repo)))
    else:
        steps.append(Step(repo, "environments", "todo" if todo_envs else "ok",
                          ("create or fix: " + ", ".join(
                              e["name"] + (f" (reviewer: {ctx.login})" if e["human_reviewer_required"] else "")
                              for e in todo_envs)) if todo_envs else ", ".join(e["name"] for e in envs),
                          make_environments if todo_envs else None))

    # --- product: security --------------------------------------------
    if w.vulnerability_alerts(repo):
        steps.append(Step(repo, "Dependabot alerts and security updates", "ok", "enabled"))
    else:
        steps.append(Step(repo, "Dependabot alerts and security updates", "todo", "enable",
                          lambda: (w.enable_security(repo), "enabled")[1]))
    codeql = w.codeql_state(repo)
    if codeql == "configured":
        steps.append(Step(repo, "CodeQL", "ok", "default setup configured"))
    elif limited and meta["private"]:
        steps.append(Step(repo, "CodeQL", "manual",
                          "code scanning on a private repo needs GitHub Advanced Security. " + PLAN_FIX.format(repo=repo)))
    else:
        steps.append(Step(repo, "CodeQL", "todo", "enable default setup (once the repo has code; "
                          "the workflows above count)", lambda: w.enable_codeql(repo)))

    # --- product: branch protection -----------------------------------
    contexts = set(((protection or {}).get("required_status_checks") or {}).get("contexts") or [])
    enforce = (protection or {}).get("enforce_admins")
    enforced = bool(enforce.get("enabled")) if isinstance(enforce, dict) else bool(enforce)
    conv = bool(((protection or {}).get("required_conversation_resolution") or {}).get("enabled"))
    if limited:
        steps.append(Step(repo, "branch protection", "manual",
                          f"`{', '.join(REQUIRED_CHECKS)}` run but cannot be required. " + PLAN_FIX.format(repo=repo)))
    elif protection and set(REQUIRED_CHECKS) <= contexts and enforced and conv:
        steps.append(Step(repo, "branch protection", "ok", f"requires {', '.join(REQUIRED_CHECKS)}; admins enforced"))
    else:
        steps.append(Step(repo, "branch protection", "todo",
                          f"require {', '.join(REQUIRED_CHECKS)}, enforce for admins, require conversation resolution",
                          lambda: w.put_protection(repo, list(REQUIRED_CHECKS))))

    # --- board ----------------------------------------------------------
    template = ((products.get("products") or {}).get(w.control_plane_key(cp, products)) or {}).get("project")
    project = (entry or {}).get("project") if entry and (entry.get("project") or {}).get("number") else None
    title = f"{key} Delivery"
    if not project:
        found = w.find_project(repo.split("/")[0], title)
        project = {"owner": repo.split("/")[0], "number": found} if found else None
    if project:
        ctx.project = project
        steps.append(Step(repo, "board", "ok", f"Projects #{project['number']} ({title})"))
    elif template:
        def make_board():
            number = w.copy_project(template["owner"], template["number"], repo.split("/")[0], title)
            w.link_project(repo.split("/")[0], number, repo)
            ctx.project = {"owner": repo.split("/")[0], "number": number}
            return f"created Projects #{number} and linked it to {repo}"
        steps.append(Step(repo, "board", "todo",
                          f"copy Projects #{template['number']} (fields included) as \"{title}\", link to {repo}",
                          make_board))
    else:
        steps.append(Step(repo, "board", "manual", "no control-plane board to copy fields from"))

    # --- tracker: interview + registry ----------------------------------
    issue = w.find_issue(cp, f"product:{key}", INTERVIEW_TITLE.format(key=key))
    if issue:
        ctx.interview = issue["number"]
        steps.append(Step(cp, "interview issue", "ok", f"#{issue['number']}"))
    else:
        def make_issue():
            ctx.interview = w.create_issue(cp, INTERVIEW_TITLE.format(key=key), interview_body(key, repo),
                                           [f"product:{key}", "role:product-manager", "type:story"])
            return f"opened #{ctx.interview}"
        steps.append(Step(cp, "interview issue", "todo",
                          f"open \"{INTERVIEW_TITLE.format(key=key)}\" for the product-manager", make_issue))

    if entry:
        steps.append(Step(cp, "products.yaml entry", "ok" if entry.get("bootstrapped") else "manual",
                          "on main, bootstrapped" if entry.get("bootstrapped") else
                          "on main but `bootstrapped: false`; rerun after fixing what readiness reports"))
    else:
        pr = w.find_pr(cp, REGISTRY_BRANCH.format(key=key))
        if pr:
            steps.append(Step(cp, "products.yaml entry", "waiting", f"PR open, merge it: {pr}"))
        else:
            def make_pr():
                floor = bootstrap.is_ok(bootstrap.do_check(repo, "dod", get_file=w.get_file,
                                                           get_protection=w.protection,
                                                           get_repo_meta=lambda r: w.repo(r)))
                text = w.registry_text(cp) + registry_entry(key, repo, ctx.project, envs, floor, ctx.today)
                return w.open_registry_pr(cp, key, repo, text, ctx.interview)
            steps.append(Step(cp, "products.yaml entry", "todo",
                              f"open a PR adding `{key}` (bootstrapped only if the floor verifies)", make_pr))

    # --- the first dispatch -------------------------------------------
    if entry and entry.get("bootstrapped"):
        if issue and ("status:ready" in issue["labels"] or "status:in-progress" in issue["labels"]
                      or issue.get("dispatched")):
            steps.append(Step(cp, "first dispatch", "ok", f"#{issue['number']} is approved and dispatched"))
        else:
            # The interview may be opened by this same run, so the number is
            # read when the step applies, not when it is planned.
            steps.append(Step(cp, "first dispatch", "todo",
                              f"label the interview status:ready and dispatch it as product-manager on {key}",
                              lambda: w.approve_and_dispatch(cp, ctx.interview, key)))
    else:
        steps.append(Step(cp, "first dispatch", "waiting",
                          "after the products.yaml PR merges, rerun to dispatch the interview"))
    return steps


def readiness(w, ctx: Ctx, steps: list[Step]) -> list[tuple[str, bool, str]]:
    """Can an agent build and test this unattended? Every setup step, plus
    the one thing setup cannot install: a build with tests."""
    out = [(f"{s.title} ({s.where})", s.status == "ok", s.detail) for s in steps]
    root = w.root_files(ctx.repo)
    manifests = [m for m in BUILD_MANIFESTS if m in root]
    tests = [d for d in TEST_DIRS if d in root]
    if manifests and tests:
        out.append(("build and tests an agent can run", True, f"{', '.join(manifests)}; {', '.join(tests)}/"))
    else:
        only_setup = not (root - {"CONVENTIONS.md", ".github"})
        out.append(("build and tests an agent can run", False,
                    "no code yet; the interview's first story scaffolds a build and a test" if only_setup
                    else f"found manifests {manifests or 'none'} and test dirs {tests or 'none'}"))
    return out


def render_plan(steps: list[Step]) -> str:
    mark = {"ok": "ok     ", "todo": "TODO   ", "waiting": "waiting", "manual": "MANUAL ",
            "blocked": "BLOCKED", "unverified": "check  "}
    return "\n".join(f"  {mark[s.status]} [{s.where}] {s.title}: {s.detail}" for s in steps)


# --------------------------------------------------------------------------
# The world — gh, isolated so tests never call it.
# --------------------------------------------------------------------------

def gh(args: list[str], stdin: Optional[str] = None, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True, cwd=REPO_ROOT)
    if check and proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])} failed: {proc.stderr.strip()}")
    return proc


def gh_json(args: list[str], check: bool = True):
    proc = gh(args, check=check)
    return json.loads(proc.stdout) if proc.returncode == 0 and proc.stdout.strip() else None


class GitHub:
    def whoami(self) -> str:
        return gh(["api", "user", "--jq", ".login"]).stdout.strip()

    def repo(self, repo: str) -> Optional[dict]:
        data = gh_json(["api", f"repos/{repo}"], check=False)
        if not data:
            return None
        empty = gh(["api", f"repos/{repo}/commits?per_page=1"], check=False).returncode != 0
        return {"default_branch": data["default_branch"], "admin": bool((data.get("permissions") or {}).get("admin")),
                "is_admin": bool((data.get("permissions") or {}).get("admin")),
                "empty": empty, "owner_type": data["owner"]["type"], "private": data["private"]}

    def secret_names(self, repo: str) -> set[str]:
        return {s["name"] for s in gh_json(["secret", "list", "--repo", repo, "--json", "name"]) or []}

    def variable(self, repo: str, name: str) -> Optional[str]:
        proc = gh(["variable", "get", name, "--repo", repo], check=False)
        return proc.stdout.strip() if proc.returncode == 0 else None

    def set_variable(self, repo: str, name: str, value: str) -> None:
        gh(["variable", "set", name, "--repo", repo, "--body", value])

    def label_names(self, repo: str) -> set[str]:
        return {l["name"] for l in gh_json(["label", "list", "--repo", repo, "--limit", "500", "--json", "name"]) or []}

    def create_label(self, repo: str, name: str, color: str, description: str) -> None:
        gh(["label", "create", name, "--repo", repo, "--color", color, "--description", description])

    def get_file(self, repo: str, path: str) -> Optional[str]:
        proc = gh(["api", f"repos/{repo}/contents/{path}"], check=False)
        if proc.returncode != 0:
            # 404 for a missing file; an empty repo answers 404 too.
            if "404" in proc.stderr or "Not Found" in proc.stderr or "empty" in proc.stderr.lower():
                return None
            raise RuntimeError(f"GET {path} on {repo} failed: {proc.stderr.strip()}")
        data = json.loads(proc.stdout)
        if isinstance(data, list):
            return ""
        return base64.b64decode(data["content"]).decode()

    def put_file(self, repo: str, path: str, content: str, message: str) -> None:
        bootstrap.api_put_file(repo, path, content, message)

    def root_files(self, repo: str) -> set[str]:
        data = gh_json(["api", f"repos/{repo}/contents/"], check=False)
        return {e["name"] for e in data} if isinstance(data, list) else set()

    def environments(self, repo: str) -> dict[str, list]:
        data = gh_json(["api", f"repos/{repo}/environments"], check=False) or {}
        out = {}
        for env in data.get("environments") or []:
            reviewers = [r for rule in env.get("protection_rules") or [] if rule.get("type") == "required_reviewers"
                         for r in rule.get("reviewers") or []]
            out[env["name"]] = reviewers
        return out

    def put_environment(self, repo: str, name: str, reviewer_logins: list[str]) -> str:
        """Returns a note when the plan refused the reviewer. `reviewers: null`
        counts as a protection rule to GitHub, so no reviewers means no key."""
        body = {}
        if reviewer_logins:
            body["reviewers"] = [{"type": "User", "id": int(gh(["api", f"users/{l}", "--jq", ".id"]).stdout)}
                                 for l in reviewer_logins]
        proc = gh(["api", "-X", "PUT", f"repos/{repo}/environments/{name}", "--input", "-"],
                  stdin=json.dumps(body), check=False)
        if proc.returncode == 0:
            return ""
        if body and any(m in proc.stderr for m in PLAN_LIMITED):
            gh(["api", "-X", "PUT", f"repos/{repo}/environments/{name}", "--input", "-"], stdin="{}")
            return f"{name} created without its required reviewer (plan limit)"
        raise RuntimeError(f"PUT environment {name} on {repo} failed: {proc.stderr.strip()}")

    def vulnerability_alerts(self, repo: str) -> bool:
        return gh(["api", f"repos/{repo}/vulnerability-alerts"], check=False).returncode == 0

    def enable_security(self, repo: str) -> None:
        gh(["api", "-X", "PUT", f"repos/{repo}/vulnerability-alerts"])
        gh(["api", "-X", "PUT", f"repos/{repo}/automated-security-fixes"])

    def codeql_state(self, repo: str) -> Optional[str]:
        data = gh_json(["api", f"repos/{repo}/code-scanning/default-setup"], check=False)
        return (data or {}).get("state")

    def enable_codeql(self, repo: str) -> str:
        proc = gh(["api", "-X", "PATCH", f"repos/{repo}/code-scanning/default-setup", "-f", "state=configured"],
                  check=False)
        if proc.returncode == 0:
            return "default setup configured"
        return f"deferred: {proc.stderr.strip()[:160]} (rerun once the repo has code)"

    def protection(self, repo: str, branch: str) -> Optional[dict]:
        try:
            return bootstrap.api_get_protection(repo, branch)
        except RuntimeError as exc:
            if any(m in str(exc) for m in PLAN_LIMITED):
                return {"unavailable": str(exc)}
            raise

    def put_protection(self, repo: str, contexts: list[str]) -> str:
        meta = self.repo(repo)
        existing = self.protection(repo, meta["default_branch"])
        for c in contexts:
            bootstrap.api_put_protection(repo, meta["default_branch"], c, existing=existing)
            existing = self.protection(repo, meta["default_branch"])
        return f"{meta['default_branch']} requires {', '.join(contexts)}"

    def control_plane_key(self, cp: str, products: dict) -> Optional[str]:
        for key, entry in (products.get("products") or {}).items():
            if isinstance(entry, dict) and str(entry.get("repo", "")).lower() == cp.lower():
                return key
        return None

    def find_project(self, owner: str, title: str) -> Optional[int]:
        data = gh_json(["project", "list", "--owner", owner, "--limit", "200", "--format", "json"], check=False) or {}
        for p in data.get("projects") or []:
            if p.get("title") == title and not p.get("closed"):
                return int(p["number"])
        return None

    def copy_project(self, src_owner: str, src_number: int, owner: str, title: str) -> int:
        data = gh_json(["project", "copy", str(src_number), "--source-owner", src_owner,
                        "--target-owner", owner, "--title", title, "--format", "json"])
        return int(data["number"])

    def link_project(self, owner: str, number: int, repo: str) -> None:
        gh(["project", "link", str(number), "--owner", owner, "--repo", repo])

    def find_issue(self, repo: str, label: str, title: str) -> Optional[dict]:
        data = gh_json(["issue", "list", "--repo", repo, "--state", "open", "--label", label,
                        "--limit", "50", "--json", "number,title,labels"], check=False) or []
        for i in data:
            if i["title"] == title:
                comments = gh_json(["api", f"repos/{repo}/issues/{i['number']}/comments", "--jq",
                                    "[.[] | select(.user.login == \"github-actions[bot]\") | .body | "
                                    "select(startswith(\"<!-- foundry:dispatch-start\"))] | length"],
                                   check=False)
                return {"number": i["number"], "labels": [l["name"] for l in i["labels"]],
                        "dispatched": bool(comments)}
        return None

    def create_issue(self, repo: str, title: str, body: str, labels: list[str]) -> int:
        args = ["issue", "create", "--repo", repo, "--title", title, "--body", body]
        for l in labels:
            args += ["--label", l]
        url = gh(args).stdout.strip()
        return int(url.rstrip("/").rsplit("/", 1)[1])

    def registry(self, cp: str) -> dict:
        import yaml
        return yaml.safe_load(self.registry_text(cp)) or {}

    def registry_text(self, cp: str) -> str:
        text = self.get_file(cp, "policies/products.yaml")
        if text is None:
            raise RuntimeError(f"{cp} has no policies/products.yaml")
        return text

    def find_pr(self, repo: str, head: str) -> Optional[str]:
        data = gh_json(["pr", "list", "--repo", repo, "--head", head, "--state", "open", "--json", "url"],
                       check=False) or []
        return data[0]["url"] if data else None

    def open_registry_pr(self, cp: str, key: str, repo: str, text: str, interview: Optional[int]) -> str:
        branch = REGISTRY_BRANCH.format(key=key)
        base = gh_json(["api", f"repos/{cp}"])["default_branch"]
        sha = gh(["api", f"repos/{cp}/git/ref/heads/{base}", "--jq", ".object.sha"]).stdout.strip()
        if gh(["api", f"repos/{cp}/git/ref/heads/{branch}"], check=False).returncode != 0:
            gh(["api", "-X", "POST", f"repos/{cp}/git/refs", "-f", f"ref=refs/heads/{branch}", "-f", f"sha={sha}"])
        blob = gh(["api", f"repos/{cp}/contents/policies/products.yaml?ref={branch}", "--jq", ".sha"]).stdout.strip()
        item = f"{cp}#{interview}" if interview else f"{cp}#323"
        message = (f"chore(products): register {key} ({repo})\n\n"
                   f"Added by scripts/foundry-init.py.\n\n"
                   f"Work-Item: {item}\nRequirement: REQ-004\nAgent-Role: human\nHarness: foundry-init\n")
        gh(["api", "-X", "PUT", f"repos/{cp}/contents/policies/products.yaml",
            "-f", f"message={message}", "-f", f"branch={branch}", "-f", f"sha={blob}",
            "-f", f"content={base64.b64encode(text.encode()).decode()}"])
        ref = f"#{interview}" if interview else "#323"
        body = (f"Registers `{key}` (`{repo}`) in `policies/products.yaml`, so dispatch can target it.\n\n"
                f"Written by `scripts/foundry-init.py`. `bootstrapped` is true only if `bootstrap-product.py`'s "
                f"governance floor verified against the live repo when this PR was opened.\n\n"
                f"Relates to {ref} — it does not close it\n\nREQ-004\n")
        return gh(["pr", "create", "--repo", cp, "--head", branch, "--base", base,
                   "--title", f"chore(products): register {key}", "--body", body]).stdout.strip()

    def approve_and_dispatch(self, cp: str, number: int, key: str) -> str:
        gh(["issue", "edit", str(number), "--repo", cp, "--add-label", "status:ready"])
        gh(["workflow", "run", "dispatch.yml", "--repo", cp, "-f", f"issue={number}",
            "-f", "role=product-manager", "-f", f"product={key}"])
        return f"#{number} labelled status:ready and dispatched"

    # --- the GitHub App ------------------------------------------------

    def app_installed(self, ctx: Ctx, repo: str) -> Optional[bool]:
        """Only answerable with the App's own key, which this process holds
        only in the run that created the App."""
        if not ctx.app:
            return None
        return repo.split("/")[1] in app_installation_repos(ctx.app, repo.split("/")[0])

    def create_app(self, ctx: Ctx) -> str:
        ctx.app = create_app_via_manifest(ctx.control_plane, self.repo(ctx.control_plane)["owner_type"])
        self.set_variable(ctx.control_plane, APP_VAR, ctx.app["client_id"])
        self.set_variable(ctx.control_plane, APP_SLUG_VAR, ctx.app["slug"])
        gh(["secret", "set", APP_SECRET, "--repo", ctx.control_plane], stdin=ctx.app["pem"])
        install = f"https://github.com/apps/{ctx.app['slug']}/installations/new"
        print(f"    install it on {ctx.control_plane} and {ctx.repo}: {install}")
        webbrowser.open(install)
        owner = ctx.repo.split("/")[0]
        need = {ctx.repo.split("/")[1], ctx.control_plane.split("/")[1]}
        for _ in range(60):
            if need <= app_installation_repos(ctx.app, owner):
                return f"created {ctx.app['slug']}[bot], stored {APP_VAR} and {APP_SECRET}, installed"
            time.sleep(5)
        return (f"created {ctx.app['slug']}[bot] and stored its credentials; the installation on "
                f"{', '.join(sorted(need))} was not seen within 5 minutes; finish it at {install}")


def create_app_via_manifest(cp: str, owner_type: str) -> dict:
    """GitHub's manifest flow: post the manifest, the owner clicks Create, and
    GitHub redirects back here with a code that converts once into the App's
    credentials. The private key goes from that response straight into
    `gh secret set` on stdin; it is never written to disk or printed.
    """
    owner = cp.split("/")[0]
    manifest = json.loads(MANIFEST_PATH.read_text())
    manifest["name"] = f"foundry-{owner.lower()}"[:34]
    manifest["url"] = f"https://github.com/{cp}"
    manifest["redirect_url"] = f"http://127.0.0.1:{MANIFEST_PORT}/created"
    state = pysecrets.token_urlsafe(16)
    target = (f"https://github.com/organizations/{owner}/settings/apps/new" if owner_type == "Organization"
              else "https://github.com/settings/apps/new") + f"?state={state}"
    got: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            if url.path == "/created":
                q = urllib.parse.parse_qs(url.query)
                if q.get("state", [""])[0] == state and q.get("code"):
                    got["code"] = q["code"][0]
                    page = "<p>Foundry App created. Return to the terminal.</p>"
                else:
                    page = "<p>State mismatch; ignored.</p>"
            else:
                value = json.dumps(manifest).replace("&", "&amp;").replace('"', "&quot;")
                page = (f'<form id="f" method="post" action="{target}">'
                        f'<input type="hidden" name="manifest" value="{value}">'
                        f'<button>Create the Foundry GitHub App</button></form>'
                        f'<script>document.getElementById("f").submit()</script>')
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(page.encode())

    server = http.server.HTTPServer(("127.0.0.1", MANIFEST_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"    opening the browser: confirm the App on GitHub (http://127.0.0.1:{MANIFEST_PORT}/)")
    webbrowser.open(f"http://127.0.0.1:{MANIFEST_PORT}/")
    for _ in range(600):
        if "code" in got:
            break
        time.sleep(0.5)
    server.shutdown()
    if "code" not in got:
        raise RuntimeError("no App was created within 5 minutes")
    data = gh_json(["api", "-X", "POST", f"app-manifests/{got['code']}/conversions"])
    return {k: data[k] for k in ("id", "slug", "client_id", "pem", "html_url")}


def app_jwt(app: dict) -> str:
    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    now = int(time.time())
    signing_input = (b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode()) + "."
                     + b64(json.dumps({"iat": now - 60, "exp": now + 540, "iss": app["client_id"]}).encode()))
    r, wfd = os.pipe()
    os.write(wfd, app["pem"].encode())
    os.close(wfd)
    try:
        sig = subprocess.run(["openssl", "dgst", "-sha256", "-sign", f"/dev/fd/{r}"], input=signing_input.encode(),
                             capture_output=True, check=True, pass_fds=(r,)).stdout
    finally:
        os.close(r)
    return signing_input + "." + b64(sig)


def app_installation_repos(app: dict, owner: str) -> set[str]:
    import urllib.request

    def call(method: str, path: str, token: str, scheme: str = "Bearer"):
        req = urllib.request.Request(f"https://api.github.com/{path}", method=method,
                                     headers={"Authorization": f"{scheme} {token}",
                                              "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read() or b"null")
    try:
        jwt = app_jwt(app)
        inst = [i for i in call("GET", "app/installations", jwt) if i["account"]["login"].lower() == owner.lower()]
        if not inst:
            return set()
        token = call("POST", f"app/installations/{inst[0]['id']}/access_tokens", jwt)["token"]
        return {r["name"] for r in call("GET", "installation/repositories?per_page=100", token, "token")["repositories"]}
    except Exception:
        return set()


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None, world=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo", help="owner/name of the product repo")
    ap.add_argument("--key", help="products.yaml key (default: the repo name)")
    ap.add_argument("--control-plane", help="owner/name of the control plane (default: foundry.yaml)")
    ap.add_argument("--plan", action="store_true", help="print the plan and readiness; change nothing")
    ap.add_argument("--yes", action="store_true", help="apply without asking")
    ap.add_argument("--create-app", action="store_true", help="create the Foundry GitHub App if it is not configured")
    args = ap.parse_args(argv)

    w = world or GitHub()
    started = time.time()
    ctx = Ctx(control_plane=args.control_plane or foundry_config.control_plane(), repo=args.repo,
              key=args.key or args.repo.split("/")[1], login=w.whoami(), create_app=args.create_app)
    steps = plan(w, ctx)
    print(f"foundry-init {ctx.repo} as `{ctx.key}` (control plane {ctx.control_plane}, as {ctx.login})\n")
    print(render_plan(steps))
    todo = [s for s in steps if s.status == "todo"]
    if any(s.status == "blocked" for s in steps):
        print("\nBlocked; nothing applied.")
        return 1
    if not todo:
        print("\nNothing to do.")
    elif args.plan:
        print(f"\n{len(todo)} change(s) planned; --plan applies nothing.")
    else:
        if not args.yes:
            if input(f"\nApply {len(todo)} change(s)? [y/N] ").strip().lower() not in ("y", "yes"):
                print("Nothing applied.")
                return 1
        print()
        failures = 0
        for s in todo:
            try:
                print(f"  done    [{s.where}] {s.title}: {s.apply()}")
            except Exception as exc:  # report every failure; later steps may not depend on it
                failures += 1
                print(f"  FAILED  [{s.where}] {s.title}: {exc}")
        if failures:
            print(f"\n{failures} step(s) failed; fix and rerun (every step is idempotent).")
        steps = plan(w, ctx)

    score = readiness(w, ctx, steps)
    passed = sum(1 for _, ok, _ in score if ok)
    print(f"\nReadiness {passed}/{len(score)}:")
    for name, ok, detail in score:
        print(f"  {'yes' if ok else 'no '}  {name}: {detail}")
    print(f"\n({time.time() - started:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
