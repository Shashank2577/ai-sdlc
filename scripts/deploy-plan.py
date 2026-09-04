#!/usr/bin/env python3
"""Render the promotion plan for a dispatched deploy, and optionally the
rollback-plan artifact that goes with it.

Used by `.github/workflows/deploy.yml`. Every fact this prints is read at
run time from `policies/environments.yaml` (the ladder: order, reviewer
requirement, rollback owner) and `infra/promotion-manifest.yaml` (the
artifact, or lack of one) — nothing about the ladder or the artifact is
hardcoded here, so the workflow stays honest as those files change.

The deploy step this backs is an intentional no-op: this repository has
no deployable application. Printing that plainly, every run, is the
point — see policies/environments.yaml's own note on why two earlier
proxies for REQ-010 were rejected for implying otherwise.

    deploy-plan.py --target prod
    deploy-plan.py --target staging --rollback-out rollback-plan.md
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_POLICY = REPO_ROOT / "policies" / "environments.yaml"
DEFAULT_MANIFEST = REPO_ROOT / "infra" / "promotion-manifest.yaml"


def load_yaml(path: Path, what: str) -> dict:
    try:
        import yaml
    except ImportError:  # pragma: no cover
        sys.exit("deploy-plan: PyYAML is required")
    if not path.is_file():
        sys.exit(f"deploy-plan: {what} not found at {path}")
    return yaml.safe_load(path.read_text()) or {}


def build_report(policy: dict, manifest: dict, target: str) -> tuple[str, list[str]]:
    """Return (report_text, violations). Non-empty violations means the
    target is invalid and no deploy should proceed."""
    environments = policy.get("environments") or {}
    order = policy.get("promotion_order") or []

    if target not in environments or target not in order:
        known = sorted(set(environments) | set(order))
        return "", [
            f"{target!r} is not an environment declared in policies/environments.yaml "
            f"(known: {known})"
        ]

    env = environments[target]
    source = env.get("promotes_from")
    reviewer_required = bool(env.get("human_reviewer_required"))
    rollback = env.get("rollback") or {}

    app = manifest.get("application")
    note = manifest.get("note", "")

    lines = [
        f"Deploy dispatch -> target: {target}",
        f"Promotion order (policies/environments.yaml): {' -> '.join(order)}",
    ]
    if source is None:
        lines.append(f"Source environment: none -- {target!r} is the entry point of the ladder")
    else:
        lines.append(f"Source environment: {source}")
    lines.append(
        f"Human reviewer required for `{target}`: {reviewer_required} "
        "(enforced by the GitHub Environment's protection rule, not this workflow)"
    )
    lines.append("")
    lines.append(f"Artifact being promoted: {app if app else 'none'}")
    if note:
        lines.append(f"  {note}")
    lines.append("")
    lines.append(">>> NO APPLICATION IS DEPLOYED BY THIS RUN. <<<")
    lines.append(
        "This step is an intentional no-op: this repository has no deployable "
        "application yet. It exists to exercise the gated promotion pipeline "
        "(REQ-010) honestly -- the environment gate, the promotion order, and "
        "the rollback plan below are all real. When an application exists, "
        "this is where its actual deploy command replaces this message."
    )
    lines.append("")
    lines.append(f"Rollback plan (policies/environments.yaml -> environments.{target}.rollback):")
    lines.append(f"  Owner: {rollback.get('owner', '(none declared)')}")
    lines.append(f"  Expectation: {rollback.get('expectation', '(none declared)')}")

    return "\n".join(lines), []


def rollback_markdown(policy: dict, target: str, env_vars: dict) -> str:
    env = (policy.get("environments") or {})[target]
    rollback = env.get("rollback") or {}
    run_url = ""
    repo = env_vars.get("GITHUB_REPOSITORY")
    run_id = env_vars.get("GITHUB_RUN_ID")
    server = env_vars.get("GITHUB_SERVER_URL")
    if repo and run_id and server:
        run_url = f"{server}/{repo}/actions/runs/{run_id}"

    lines = [
        f"# Rollback plan -- {target}",
        "",
        "No application was deployed by this run (see the deploy step's output) "
        "-- there is nothing to roll back yet. This artifact records what a "
        "rollback of this environment requires, per policies/environments.yaml, "
        "so the plan exists before it is ever needed.",
        "",
        f"- **Environment:** {target}",
        f"- **Owner:** {rollback.get('owner', '(none declared)')}",
        f"- **Expectation:** {rollback.get('expectation', '(none declared)')}",
    ]
    if run_url:
        lines.append(f"- **Run:** {run_url}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", required=True, help="environment being deployed to")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--rollback-out", type=Path, default=None,
                         help="also write the rollback-plan artifact to this path")
    args = parser.parse_args(argv)

    policy = load_yaml(args.policy, "policies/environments.yaml")
    manifest = load_yaml(args.manifest, "infra/promotion-manifest.yaml")

    report, violations = build_report(policy, manifest, args.target)
    if violations:
        for v in violations:
            print(f"FAIL: {v}", file=sys.stderr)
        return 1

    print(report)

    if args.rollback_out is not None:
        args.rollback_out.parent.mkdir(parents=True, exist_ok=True)
        args.rollback_out.write_text(rollback_markdown(policy, args.target, os.environ))

    return 0


if __name__ == "__main__":
    sys.exit(main())
