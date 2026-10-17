#!/usr/bin/env python3
"""The assignment loop: read the board, dispatch what fits under the WIP limit.

Rules live in `role-packs/orchestrator/policy.yaml`, not here. The
selection itself is a pure function of the board, so two runs against the
same board always make the same decisions.

    assign.py --dry-run            # compute and print, dispatch nothing
    assign.py                      # dispatch

Exits 0 with no output on the tracker when nothing is eligible. A loop
that announces "nothing to do" every fifteen minutes gets muted, and then
it is not there when it says something real.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = REPO_ROOT / "role-packs" / "orchestrator" / "policy.yaml"
PRODUCTS_PATH = REPO_ROOT / "policies" / "products.yaml"
PRODUCT_PREFIX = "product:"
FALLBACK_PRODUCT = "foundry-program"

# The board this loop was written for: one product, the control plane. What
# a caller that passes no registry gets, and what a missing or unreadable
# `policies/products.yaml` reads as — never a guess at a second product.
SINGLE_PRODUCT = {"default": FALLBACK_PRODUCT, "products": {FALLBACK_PRODUCT: {}}}

# Used only if the pack is missing entirely. Conservative on purpose: a
# broken policy read must not become an unbounded loop.
FALLBACK_POLICY = {
    "wip": {"limit": 1, "counts": ["status:in-progress"], "per_role": {}},
    "routing": {"prefix": "role:", "supported": ["developer"], "default": None},
    "eligibility": {
        "require_labels": ["status:ready"],
        "exclude_labels": ["needs-human", "status:blocked", "qa:rejected"],
        "require_open": True,
    },
}


def load_policy(path: Path = POLICY_PATH) -> tuple[dict, str]:
    if not path.is_file():
        return FALLBACK_POLICY, f"fallback (no {path.name})"
    try:
        import yaml
        data = yaml.safe_load(path.read_text()) or {}
    except ImportError:
        sys.exit("assign: PyYAML is required to read the orchestrator policy")
    policy = {k: data.get(k, FALLBACK_POLICY[k]) for k in FALLBACK_POLICY}
    if not isinstance(policy["wip"].get("limit"), int) or policy["wip"]["limit"] < 0:
        sys.exit("assign: wip.limit must be a non-negative integer")
    return policy, str(path.relative_to(REPO_ROOT))


# --------------------------------------------------------------------------
# Selection — pure. Board in, plan out.
# --------------------------------------------------------------------------

def labels_of(issue: dict) -> set[str]:
    return {lbl["name"] for lbl in issue.get("labels", [])}


def role_of(issue: dict, routing: dict) -> str | None:
    prefix = routing.get("prefix", "role:")
    found = sorted(n[len(prefix):] for n in labels_of(issue) if n.startswith(prefix))
    if len(found) != 1:
        # Zero is unrefined; two is a contradiction. Neither is a guess we
        # are entitled to make.
        return None
    return found[0] if found[0] in routing.get("supported", []) else None


@functools.lru_cache(maxsize=None)
def dispatchable_from(role: str) -> tuple[str, ...] | None:
    """The states `role-packs/<role>/pack.yaml` declares this role may be
    dispatched from — the same declaration `dispatch.yml`'s guard reads via
    the compiler (#67). None means the pack declares nothing (or cannot be
    read), and the caller falls back to `eligibility.require_labels`: that
    fallback is for a silent pack, not the rule for every role.
    """
    path = REPO_ROOT / "role-packs" / role / "pack.yaml"
    if not path.is_file():
        return None
    try:
        import yaml
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:
        return None
    states = data.get("dispatchable_from")
    if not isinstance(states, list) or not states or not all(isinstance(s, str) for s in states):
        return None
    return tuple(states)


def default_product(products: dict, repo: str) -> str:
    """The `policies/products.yaml` key whose `repo` is the control plane's
    own repo (#208) — what an item with no `product:*` label belongs to.
    Every work item lives in the control plane whatever product it targets,
    so the control plane's own product is the only default that is not a
    guess. Deriving it from the registry means this file does not hardcode
    a product name that would go stale the moment one is renamed.
    `foundry-program` is the fallback only for an empty registry or an
    unmatched repo, both of which would otherwise leave `product` empty and
    every dispatch refused.
    """
    for key, entry in products.items():
        if isinstance(entry, dict) and repo and entry.get("repo") == repo:
            return key
    return FALLBACK_PRODUCT


def _product_labels(issue: dict) -> list[str]:
    return sorted(n[len(PRODUCT_PREFIX):] for n in labels_of(issue)
                  if n.startswith(PRODUCT_PREFIX))


def product_of(issue: dict, registry: dict | None = None) -> str | None:
    """The product an item targets (#290): its one `product:<key>` label, or
    the control plane's own product when it has none. None when the labels
    say something we cannot route — `product_reason` says what."""
    registry = registry or SINGLE_PRODUCT
    found = _product_labels(issue)
    if not found:
        return registry["default"]
    if len(found) == 1 and found[0] in registry["products"]:
        return found[0]
    return None


def product_reason(issue: dict, registry: dict | None = None) -> str | None:
    """None when `product_of` resolves. Otherwise a sentence a human can act
    on. Two labels is a contradiction and an unknown key is a typo or an
    unregistered product; routing either to some product would be a guess,
    and a wrong guess runs an agent against the wrong repo."""
    registry = registry or SINGLE_PRODUCT
    found = _product_labels(issue)
    if len(found) > 1:
        return f"several product labels ({', '.join(PRODUCT_PREFIX + k for k in found)})"
    if found and found[0] not in registry["products"]:
        return (f"product `{found[0]}` is not in policies/products.yaml "
                f"(known: {', '.join(sorted(registry['products']))})")
    return None


def open_pr_numbers(issues: list[dict], prs_by_repo: dict[str, set[int]],
                    registry: dict | None = None) -> set[int]:
    """Items with a PR in flight in their own product's repo.

    Branches are `story|bug/FDY-<issue>-<slug>` in whichever repo the
    product lives in, and the issue number is always the control plane's,
    so the same number can name unrelated branches in two repos. An item
    counts only where its product's PRs actually land: a pilot item's PR is
    in the pilot repo, and a control-plane branch that happens to share its
    number is not it.
    """
    registry = registry or SINGLE_PRODUCT
    out = set()
    for issue in issues:
        key = product_of(issue, registry)
        if key is None:
            continue
        repo = registry["products"].get(key, {}).get("repo", "")
        if issue["number"] in prs_by_repo.get(repo, set()):
            out.add(issue["number"])
    return out


def ineligible_reason(issue: dict, policy: dict, registry: dict | None = None) -> str | None:
    """None means eligible. Otherwise a sentence a human can act on."""
    elig, routing = policy["eligibility"], policy["routing"]
    names = labels_of(issue)

    if elig.get("require_open", True) and issue.get("state") != "OPEN":
        return "not open"
    blocking = [l for l in elig.get("exclude_labels", []) if l in names]
    if blocking:
        return f"carries {', '.join(blocking)}"

    prefix = routing.get("prefix", "role:")
    role_labels = [n for n in names if n.startswith(prefix)]
    if not role_labels:
        return f"no `{prefix}*` label — refinement is not finished"
    if len(role_labels) > 1:
        return f"several role labels ({', '.join(sorted(role_labels))})"
    role = role_of(issue, routing)
    if role is None:
        return (f"role `{role_labels[0][len(prefix):]}` is not dispatchable "
                f"(supported: {', '.join(routing.get('supported', []))})")
    unroutable = product_reason(issue, registry)
    if unroutable:
        return unroutable

    entry_states = dispatchable_from(role) or tuple(elig.get("require_labels", []))
    if entry_states and not (set(entry_states) & names):
        if len(entry_states) == 1:
            return f"missing {entry_states[0]}"
        return f"missing one of {', '.join(entry_states)}"
    return None


REVIEW_ROLE = "qa"
REVIEW_STATE = "status:in-review"


def review_reason(issue: dict, policy: dict, with_open_pr: set[int],
                  registry: dict | None = None) -> str | None:
    """None means the item is waiting for a QA review (#299).

    Routing follows the item's own role label, which records its author, so
    an author's finished work in review was never QA's to pick up: QA only
    ran when a person dispatched it by hand. The author's label is left as
    it is, because a rejection has to route back to that author.
    """
    names = labels_of(issue)
    if issue.get("state") != "OPEN" or REVIEW_STATE not in names:
        return f"not {REVIEW_STATE}"
    blocking = [l for l in policy["eligibility"].get("exclude_labels", []) if l in names]
    if blocking:
        return f"carries {', '.join(blocking)}"
    unroutable = product_reason(issue, registry)
    if unroutable:
        return unroutable
    if "qa:approved" in names:
        return "qa:approved — waiting on a person to merge"
    if issue["number"] not in with_open_pr:
        return "no open pull request to review"
    return None


def sort_key(issue: dict, with_open_pr: set[int]) -> tuple:
    # Finishing beats starting; then lowest number. Deterministic on purpose
    # — a clever order nobody can predict is worse than a dull one.
    return (0 if issue["number"] in with_open_pr else 1, issue["number"])


def plan(issues: list[dict], policy: dict, with_open_pr: set[int] | None = None,
         registry: dict | None = None) -> dict:
    with_open_pr = with_open_pr or set()
    wip, routing = policy["wip"], policy["routing"]
    counts = set(wip.get("counts", ["status:in-progress"]))

    in_flight = [i for i in issues
                 if i.get("state") == "OPEN" and labels_of(i) & counts]
    in_flight_by_role = {}
    for issue in in_flight:
        role = role_of(issue, routing)
        if role:
            in_flight_by_role[role] = in_flight_by_role.get(role, 0) + 1

    eligible, skipped = [], []
    for issue in issues:
        reason = ineligible_reason(issue, policy, registry)
        if reason is None:
            eligible.append(issue)
        elif issue.get("state") == "OPEN":
            skipped.append({"number": issue["number"], "title": issue.get("title", ""),
                            "reason": reason})

    slots = max(wip["limit"] - len(in_flight), 0)
    per_role = wip.get("per_role") or {}
    dispatch, deferred = [], []

    # Reviews first: finishing beats starting. In-flight QA sessions are
    # counted under their item's author role (the label WIP reads), so the
    # qa cap bounds reviews dispatched per run; an item under review sits at
    # status:in-progress and cannot be picked twice.
    eligible_numbers = {i["number"] for i in eligible}
    reviewing = set()
    if REVIEW_ROLE in routing.get("supported", []):
        review_cap = per_role.get(REVIEW_ROLE)
        for issue in sorted(issues, key=lambda i: i["number"]):
            if issue["number"] in eligible_numbers or review_reason(issue, policy, with_open_pr,
                                                                    registry):
                continue
            entry = {"number": issue["number"], "title": issue.get("title", ""),
                     "role": REVIEW_ROLE, "product": product_of(issue, registry),
                     "url": issue.get("url", "")}
            reviewing.add(issue["number"])
            if len(dispatch) >= slots:
                entry["reason"] = f"WIP limit {wip['limit']} reached"
                deferred.append(entry)
            elif review_cap is not None and in_flight_by_role.get(REVIEW_ROLE, 0) + len(dispatch) >= review_cap:
                entry["reason"] = f"per-role cap for `{REVIEW_ROLE}` is {review_cap}"
                deferred.append(entry)
            else:
                dispatch.append(entry)
    skipped = [s for s in skipped if s["number"] not in reviewing]

    for issue in sorted(eligible, key=lambda i: sort_key(i, with_open_pr)):
        role = role_of(issue, routing)
        entry = {"number": issue["number"], "title": issue.get("title", ""),
                 "role": role, "product": product_of(issue, registry),
                 "url": issue.get("url", "")}
        if len(dispatch) >= slots:
            entry["reason"] = f"WIP limit {wip['limit']} reached"
            deferred.append(entry)
            continue
        cap = per_role.get(role)
        used = in_flight_by_role.get(role, 0) + sum(1 for d in dispatch if d["role"] == role)
        if cap is not None and used >= cap:
            entry["reason"] = f"per-role cap for `{role}` is {cap}"
            deferred.append(entry)
            continue
        dispatch.append(entry)

    return {
        "limit": wip["limit"],
        "in_flight": len(in_flight),
        "in_flight_numbers": sorted(i["number"] for i in in_flight),
        "slots": slots,
        "dispatch": dispatch,
        "deferred": deferred,
        "skipped": sorted(skipped, key=lambda s: s["number"]),
        "eligible_total": len(eligible),
    }


# --------------------------------------------------------------------------
# The world
# --------------------------------------------------------------------------

def gh(args: list[str]) -> str:
    return subprocess.run(["gh", *args], cwd=REPO_ROOT, check=True,
                          capture_output=True, text=True).stdout


def collect_issues() -> list[dict]:
    return json.loads(gh(["issue", "list", "--state", "open", "--limit", "200",
                          "--json", "number,title,state,labels,url"]) or "[]")


def collect_issues_with_open_prs(repos: list[str]) -> dict[str, set[int]]:
    """Per product repo, the issue numbers that already have a branch and PR
    in flight there. An empty repo name means this checkout's own."""
    out = {}
    for repo in repos:
        pulls = json.loads(gh(["pr", "list", "--state", "open", "--limit", "100",
                               "--json", "headRefName", *(["--repo", repo] if repo else [])])
                           or "[]")
        out[repo] = set()
        for pr in pulls:
            m = re.match(r"^(?:story|bug)/FDY-(\d+)-", pr.get("headRefName", ""))
            if m:
                out[repo].add(int(m.group(1)))
    return out


def load_products(path: Path = PRODUCTS_PATH) -> dict:
    """`policies/products.yaml`'s `products:` mapping, or {} when it is
    missing or unreadable."""
    if not path.is_file():
        return {}
    try:
        import yaml
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}
    products = data.get("products")
    if not isinstance(products, dict):
        return {}
    return {key: entry for key, entry in products.items() if isinstance(entry, dict)}


@functools.lru_cache(maxsize=None)
def load_registry() -> dict:
    """The registry the pure functions above route against. This runs in the
    control plane: GH_REPO is set to it by orchestrate.yml, and
    GITHUB_REPOSITORY by Actions itself for any workflow that does not set
    GH_REPO (project-sync.yml)."""
    products = load_products()
    if not products:
        return SINGLE_PRODUCT
    repo = os.environ.get("GH_REPO") or os.environ.get("GITHUB_REPOSITORY", "")
    return {"default": default_product(products, repo), "products": products}


def dispatch_one(entry: dict) -> tuple[bool, str]:
    try:
        gh(["workflow", "run", "dispatch.yml",
            "-f", f"issue={entry['number']}", "-f", f"role={entry['role']}",
            "-f", f"product={entry['product']}"])
        return True, ""
    except subprocess.CalledProcessError as exc:
        return False, (exc.stderr or exc.stdout or "").strip().replace("\n", " ")[:300]


def render_plan(p: dict, source: str) -> str:
    lines = [
        f"Board: {p['in_flight']}/{p['limit']} in flight"
        + (f" {p['in_flight_numbers']}" if p["in_flight_numbers"] else "")
        + f", {p['slots']} slot(s) free, "
        f"{p['eligible_total']} eligible. Policy: {source}",
    ]
    for d in p["dispatch"]:
        lines.append(f"  dispatch #{d['number']} as {d['role']} on {d['product']} "
                     f"— {d['title'][:60]}")
    for d in p["deferred"]:
        lines.append(f"  defer    #{d['number']} — {d['reason']}")
    for s in p["skipped"]:
        lines.append(f"  skip     #{s['number']} — {s['reason']}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true", help="print the plan as JSON")
    args = ap.parse_args()

    policy, source = load_policy()
    registry = load_registry()
    issues = collect_issues()
    repos = sorted({entry.get("repo", "") for entry in registry["products"].values()})
    with_open_pr = open_pr_numbers(issues, collect_issues_with_open_prs(repos), registry)
    p = plan(issues, policy, with_open_pr, registry)

    if args.json:
        print(json.dumps({**p, "policy_source": source}, indent=2))
        return 0

    report = render_plan(p, source)
    print(report)

    summary = []
    if not p["dispatch"]:
        # The quiet exit. The run log says what was considered; the tracker
        # hears nothing, because there is nothing worth a notification.
        summary = ["## Assignment loop — nothing dispatched", "", "```", report, "```"]
    else:
        summary = ["## Assignment loop", "", "```", report, "```"]

    failures = 0
    if not args.dry_run:
        for entry in p["dispatch"]:
            ok, err = dispatch_one(entry)
            if ok:
                print(f"dispatched #{entry['number']} as {entry['role']} on {entry['product']}")
                summary.append(f"- dispatched #{entry['number']} as `{entry['role']}` "
                               f"on `{entry['product']}`")
            else:
                failures += 1
                print(f"FAILED to dispatch #{entry['number']}: {err}", file=sys.stderr)
                summary.append(f"- **failed** to dispatch #{entry['number']}: `{err}`")
    elif p["dispatch"]:
        summary.append("")
        summary.append("_Dry run — nothing was dispatched._")

    import os
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a") as fh:
            fh.write("\n".join(summary) + "\n")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
