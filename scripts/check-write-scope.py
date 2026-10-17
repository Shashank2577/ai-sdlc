#!/usr/bin/env python3
"""The `scope` check (ADR-0011): every file a pull request changes was
written by a role that was actually dispatched on its work item, and that
role's `write_scope` allows the file.

    check-write-scope.py --repo Shashank2577/ai-sdlc --pr 123
    check-write-scope.py --repo owner/product --pr 7 --control-plane Shashank2577/ai-sdlc
    check-write-scope.py ... --comment       # post the report on the PR when it fails

Two facts decide it, and an agent can assert neither about itself:

- **Which role wrote a commit.** The commit's `Agent-Role` trailer is a
  claim. It counts only when `dispatch.yml` posted a dispatch record for
  that role on the work item, as `github-actions[bot]` in the control
  plane, and the record names a real `dispatch.yml` run whose job is
  "#<item> as <role> on <product>". The work item comes from the branch
  name (`story/FDY-<n>-...`), which CONVENTIONS.md already requires.
- **What that role may write.** `role-packs/<role>/policy.yaml:write_scope`,
  deny before allow, plus any `write_scope_extra` allow patterns the
  product's `policies/products.yaml` entry adds. An extra can open a new
  path. It can never re-open one the pack denies.

`.github/workflows/**` gets its own message because it is ADR-0001's line:
only a devops dispatch may change a workflow. That falls out of the
write_scopes as they stand. The explicit rule keeps it true if a pack is
ever loosened by mistake.

Human commits are not scope-checked: CODEOWNERS and the human merge cover
them. A human commit on a bot-authored PR counts only when GitHub verified
its signature and resolved its author to a person. That is the one piece
of provenance an agent token cannot forge.

Run from `pull_request_target` (`.github/workflows/scope-check.yml`), so
this file and its workflow are read from the base branch and a PR cannot
weaken the copy that judges it (ADR-0009). It reads the PR through the API
and never checks out the PR's code.
"""

from __future__ import annotations

import argparse
import functools
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKS_DIR = REPO_ROOT / "role-packs"
PRODUCTS_PATH = REPO_ROOT / "policies" / "products.yaml"

_spec = importlib.util.spec_from_file_location("gate_check", Path(__file__).resolve().parent / "gate-check.py")
gate_check = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("gate_check", gate_check)
_spec.loader.exec_module(gate_check)
is_human = gate_check.is_human

DISPATCHER = "github-actions[bot]"
DISPATCH_WORKFLOW = ".github/workflows/dispatch.yml"
WORKFLOWS = ".github/workflows/"
MARKER = re.compile(r"\A<!-- foundry:dispatch-start role=(\S+) product=(\S+) run=(\d+) -->")
# Dispatch records written before the marker existed: the session-start
# table. Kept so PRs already in flight when this lands are judged on the
# record they have. The run is verified the same way either way.
LEGACY_HEADING = "### Dispatch — session start"
LEGACY_ROLE = re.compile(r"^\| Role \| `([^`]+)` \|", re.MULTILINE)
LEGACY_PRODUCT = re.compile(r"^\| Product \| `([^`]+)`", re.MULTILINE)
LEGACY_RUN = re.compile(r"^\| Run \| \S+/actions/runs/(\d+)", re.MULTILINE)
BRANCH = re.compile(r"^[a-z]+/FDY-(\d+)-")
AGENT_ROLE = re.compile(r"^Agent-Role:[ \t]*(\S+)[ \t]*$", re.MULTILINE | re.IGNORECASE)


# --------------------------------------------------------------------------
# Globs — pure. The write_scope dialect: `**`, `*`, `?`, and bash's
# extglob `!(a|b)` for one path segment, which the packs use to say
# "every other role's pack".
# --------------------------------------------------------------------------

def _segment_regex(glob: str) -> str:
    out, i = [], 0
    while i < len(glob):
        ch = glob[i]
        if glob.startswith("!(", i):
            end = glob.index(")", i)
            alts = "|".join(_segment_regex(a) for a in glob[i + 2:end].split("|"))
            out.append(rf"(?!(?:{alts})(?:/|$))[^/]*")
            i = end + 1
        elif glob.startswith("**", i):
            if glob.startswith("**/", i):
                out.append(r"(?:.*/)?")
                i += 3
            else:
                out.append(r".*")
                i += 2
        elif ch == "*":
            out.append(r"[^/]*")
            i += 1
        elif ch == "?":
            out.append(r"[^/]")
            i += 1
        else:
            out.append(re.escape(ch))
            i += 1
    return "".join(out)


@functools.lru_cache(maxsize=None)
def glob_regex(pattern: str) -> re.Pattern:
    return re.compile(rf"\A{_segment_regex(pattern)}\Z")


def glob_match(pattern: str, path: str) -> bool:
    return bool(glob_regex(pattern).match(path))


def scope_allows(scope: dict | None, path: str) -> tuple[bool, str]:
    """Deny wins over allow. No allow list at all fails closed: a pack that
    declares nothing has not been given anywhere to write.
    """
    scope = scope or {}
    for d in scope.get("deny") or []:
        if glob_match(d, path):
            return False, f"denied by `{d}`"
    allow = scope.get("allow") or []
    if not allow:
        return False, "the pack declares no `write_scope.allow`"
    for a in allow:
        if glob_match(a, path):
            return True, f"allowed by `{a}`"
    return False, "outside every `write_scope.allow` pattern"


# --------------------------------------------------------------------------
# Provenance — pure.
# --------------------------------------------------------------------------

def agent_role(message: str) -> str | None:
    """The commit's `Agent-Role`. None when absent. "!ambiguous" when two
    lines disagree, because picking one would be a guess.
    """
    roles = {m.lower() for m in AGENT_ROLE.findall(message or "")}
    if not roles:
        return None
    return roles.pop() if len(roles) == 1 else "!ambiguous"


def work_item_of(head_ref: str) -> int | None:
    m = BRANCH.match(head_ref or "")
    return int(m.group(1)) if m else None


def dispatch_claims(comments: list[dict]) -> list[dict]:
    """Every dispatch record on the work item, as {role, product, run}.
    Only comments the dispatcher itself wrote count. Anything an agent
    token posts is authored by the App, not `github-actions[bot]`.
    """
    out = []
    for c in comments:
        if ((c.get("user") or {}).get("login")) != DISPATCHER:
            continue
        body = (c.get("body") or "").lstrip("﻿")
        m = MARKER.match(body)
        if m:
            out.append({"role": m.group(1), "product": m.group(2), "run": int(m.group(3))})
            continue
        if body.startswith(LEGACY_HEADING):
            role, product, run = (LEGACY_ROLE.search(body), LEGACY_PRODUCT.search(body),
                                  LEGACY_RUN.search(body))
            if role and product and run:
                out.append({"role": role.group(1), "product": product.group(1),
                            "run": int(run.group(1))})
    return out


def run_matches(run: dict | None, jobs: list[dict], item: int, role: str, product: str) -> bool:
    """Is this a real dispatch.yml run of exactly this item, role and product?"""
    if not run or not (run.get("path") or "").endswith(DISPATCH_WORKFLOW):
        return False
    if run.get("event") != "workflow_dispatch":
        return False
    want = f"#{item} as {role} on {product}"
    return any((j.get("name") or "") == want for j in jobs)


def effective_scope(role: str, scopes: dict, extras: dict) -> dict:
    base = scopes.get(role) or {}
    return {"allow": list(base.get("allow") or []) + list(extras.get(role) or []),
            "deny": list(base.get("deny") or [])}


def evaluate(pr: dict, commits: list[dict], files: list[str], scopes: dict,
             extras: dict, dispatched: set[str]) -> dict:
    """Board in, verdict out.

    pr:        {author, item}
    commits:   [{sha, subject, role, merge, files, verified, author_login}]
    files:     the PR's net diff (both sides of a rename)
    scopes:    {role: {allow, deny}} from the packs
    extras:    {role: [allow patterns]} from the product's entry
    dispatched: roles with a verified dispatch record on this item+product
    """
    violations, notes = [], []
    bot_pr = not is_human(pr.get("author") or "")
    touched: dict[str, list[dict]] = {}

    for c in commits:
        if c["merge"]:
            continue
        for f in c["files"]:
            touched.setdefault(f, []).append(c)
        short, role = c["sha"][:7], c["role"]
        if role is None:
            violations.append(f"commit `{short}` (\"{c['subject']}\") has no `Agent-Role` "
                              f"trailer, so no role can be held to it")
        elif role == "!ambiguous":
            violations.append(f"commit `{short}` (\"{c['subject']}\") carries two different "
                              f"`Agent-Role` trailers")
        elif role == "human":
            if bot_pr and not (c["verified"] and is_human(c.get("author_login") or "")):
                violations.append(
                    f"commit `{short}` (\"{c['subject']}\") says `Agent-Role: human` on a PR "
                    f"opened by `{pr['author']}`. On an agent's PR, a human commit counts only "
                    f"when GitHub verified its signature to a person's account")
        elif role not in scopes:
            violations.append(f"commit `{short}` names role `{role}`, which has no pack")
        elif pr.get("item") is None:
            violations.append(f"commit `{short}` claims role `{role}`, but the branch does not "
                              f"name a work item (`story/FDY-<n>-...`), so there is no dispatch "
                              f"record to check the claim against")
        elif role not in dispatched:
            have = ", ".join(sorted(dispatched)) or "none"
            violations.append(f"commit `{short}` claims role `{role}`, but no `{role}` session "
                              f"was dispatched on #{pr['item']} for this product (dispatched: "
                              f"{have})")

    for path in sorted(set(files)):
        writers = touched.get(path)
        if not writers:
            violations.append(f"`{path}` changes only in a merge commit, so no role can be "
                              f"held to it — rebase or recommit it")
            continue
        for c in writers:
            role = c["role"]
            if role in (None, "!ambiguous", "human") or role not in scopes:
                continue  # already reported, or a human's own change
            if path.startswith(WORKFLOWS) and role != "devops":
                violations.append(f"`{path}` is a workflow; only a devops dispatch may change "
                                  f"one (ADR-0001), but commit `{c['sha'][:7]}` is `{role}`")
                continue
            ok, why = scope_allows(effective_scope(role, scopes, extras), path)
            if not ok:
                violations.append(f"`{path}` is outside `{role}`'s write_scope ({why}), "
                                  f"changed in commit `{c['sha'][:7]}`")

    roles = sorted({c["role"] for c in commits if not c["merge"] and c["role"]})
    notes.append(f"PR by `{pr.get('author')}` ({'agent' if bot_pr else 'human'}); work item "
                 f"{'#' + str(pr['item']) if pr.get('item') else 'none'}; commit roles: "
                 f"{', '.join(roles) or 'none'}; dispatched: {', '.join(sorted(dispatched)) or 'none'}")
    return {"ok": not violations, "violations": violations, "notes": notes}


def render(verdict: dict) -> str:
    lines = ["<!-- foundry:scope -->", "### Scope check (ADR-0011)", ""]
    lines += [f"_{n}_" for n in verdict["notes"]]
    lines.append("")
    if verdict["ok"]:
        lines.append("Every changed file was written by a dispatched role allowed to write it.")
    else:
        lines.append("**Failed.** Each line names the file or commit and what to do about it:")
        lines.append("")
        lines += [f"- {v}" for v in verdict["violations"]]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# The world
# --------------------------------------------------------------------------

def load_yaml(path: Path) -> dict:
    import yaml
    return yaml.safe_load(path.read_text()) or {}


def load_scopes(packs_dir: Path = PACKS_DIR) -> dict:
    out = {}
    for policy in sorted(packs_dir.glob("*/policy.yaml")):
        out[policy.parent.name] = (load_yaml(policy).get("write_scope") or {})
    return out


def product_of(repo: str, products: dict) -> tuple[str | None, dict]:
    for key, entry in (products.get("products") or {}).items():
        if isinstance(entry, dict) and str(entry.get("repo", "")).lower() == repo.lower():
            return key, entry
    return None, {}


def gh_json(path: str, paginate: bool = False):
    args = ["gh", "api", path] + (["--paginate", "--slurp"] if paginate else [])
    out = subprocess.run(args, check=True, capture_output=True, text=True).stdout
    data = json.loads(out or "null")
    if paginate:
        flat = []
        for page in data or []:
            flat.extend(page if isinstance(page, list) else page.get("jobs") or [])
        return flat
    return data


def collect(repo: str, pr_number: int, control_plane: str) -> tuple[dict, list, list, set, str | None, dict]:
    products = load_yaml(PRODUCTS_PATH)
    product, entry = product_of(repo, products)
    pr_data = gh_json(f"repos/{repo}/pulls/{pr_number}")
    pr = {"author": pr_data["user"]["login"], "item": work_item_of(pr_data["head"]["ref"])}

    commits = []
    for c in gh_json(f"repos/{repo}/pulls/{pr_number}/commits", paginate=True):
        detail = gh_json(f"repos/{repo}/commits/{c['sha']}")
        paths = []
        for f in detail.get("files") or []:
            paths.append(f["filename"])
            if f.get("previous_filename"):
                paths.append(f["previous_filename"])
        message = c["commit"]["message"]
        commits.append({
            "sha": c["sha"],
            "subject": message.splitlines()[0] if message else "",
            "role": agent_role(message),
            "merge": len(c.get("parents") or []) > 1,
            "files": paths,
            "verified": bool(((c["commit"].get("verification") or {}).get("verified"))),
            "author_login": (c.get("author") or {}).get("login") or "",
        })

    files = []
    for f in gh_json(f"repos/{repo}/pulls/{pr_number}/files", paginate=True):
        files.append(f["filename"])
        if f.get("previous_filename"):
            files.append(f["previous_filename"])

    dispatched: set[str] = set()
    if pr["item"] is not None and product:
        comments = gh_json(f"repos/{control_plane}/issues/{pr['item']}/comments", paginate=True)
        for claim in dispatch_claims(comments):
            if claim["product"] != product or claim["role"] in dispatched:
                continue
            try:
                run = gh_json(f"repos/{control_plane}/actions/runs/{claim['run']}")
                jobs = gh_json(f"repos/{control_plane}/actions/runs/{claim['run']}/jobs", paginate=True)
            except subprocess.CalledProcessError:
                continue  # a run that cannot be read is not evidence
            if run_matches(run, jobs, pr["item"], claim["role"], product):
                dispatched.add(claim["role"])
    return pr, commits, files, dispatched, product, entry


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True, help="owner/name of the repo the PR is in")
    ap.add_argument("--pr", required=True, type=int)
    ap.add_argument("--control-plane", default=os.environ.get("GITHUB_REPOSITORY", ""),
                    help="owner/name holding the work items and dispatch.yml (default: this repo)")
    ap.add_argument("--comment", action="store_true", help="post the report on the PR when it fails")
    args = ap.parse_args()

    pr, commits, files, dispatched, product, entry = collect(args.repo, args.pr, args.control_plane)
    if product is None:
        verdict = {"ok": False, "notes": [f"repo `{args.repo}`"], "violations": [
            f"`{args.repo}` is not a registered product in policies/products.yaml, so no role's "
            f"scope can be resolved for it"]}
    else:
        verdict = evaluate(pr, commits, files, load_scopes(), entry.get("write_scope_extra") or {},
                           dispatched)
    report = render(verdict)
    print(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as fh:
            fh.write(report + "\n")
    if args.comment and not verdict["ok"]:
        subprocess.run(["gh", "pr", "comment", str(args.pr), "--repo", args.repo, "--body", report],
                       check=False)
    return 0 if verdict["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
