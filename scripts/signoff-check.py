#!/usr/bin/env python3
"""Validate policies/signoff.yaml, and classify one item's sign-off state.

Two independent jobs, one script:

Policy validation (offline, no API call) — `--validate-policy` or no mode
at all:
  - every scope under `signoffs` (and `change_request`) declares `owner`,
    `granted_by`, `default_if_unanswered`, `sla_hours`, `escalates_after_sla`
    and `enforced_by: [signoff_check]`
  - `owner` never names an agent role — `client` (or, for `change_request`,
    a human account lead) is the whole point of this gate; if an agent role
    could satisfy it, it would not be a client sign-off
  - `signoffs.*.evidence_required` and `change_request.requires` are
    non-empty lists

Classification — `--classify --issue N --scope {story,sprint,release}`:
  reads the issue's current labels and its `labeled` event history (who
  applied what, from the GitHub event payload — never from anything an
  agent could assert about itself) and reports one of:

    signed             signoff:approved, applied by a person
    change-requested   signoff:change-requested is present
    unsigned           neither label present, OR signoff:approved was
                        applied by a bot actor — REJECTED, not a valid
                        sign-off, and reported as unsigned rather than
                        silently ignored
    undetermined        signoff:approved is present but no labeling event
                        names who applied it — never rendered as accepted

Bot rejection reuses `gate-check.py`'s `is_human()` rather than a second
identity rule that could drift from it — sign-off enforcement is the same
mechanism as `dispatch_approval`: a label is not proof, the identity of
whoever applied it is (ADR-0007).

    signoff-check.py                                   # validate the real policy
    signoff-check.py --classify --issue 42 --scope story

`--classify` exits 0 when the state is `signed`, 1 otherwise — a signed
scope is the only state that means the client actually accepted it, so
that is the only state a caller gating on this script should treat as a
pass.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
SIGNOFF_POLICY = REPO_ROOT / "policies" / "signoff.yaml"

AGENT_ROLES = {
    "orchestrator", "pm", "architect", "developer", "qa", "devops",
    "techwriter", "delivery-lead",
}

STATE_SIGNED = "signed"
STATE_CHANGE_REQUESTED = "change-requested"
STATE_UNSIGNED = "unsigned"
STATE_UNDETERMINED = "undetermined"

APPROVED_LABEL = "signoff:approved"
CHANGE_REQUESTED_LABEL = "signoff:change-requested"


def _load_gate_check():
    """`is_human()`, reused rather than reimplemented — the two scripts
    must never drift on what counts as a bot actor."""
    spec = importlib.util.spec_from_file_location(
        "gate_check", REPO_ROOT / "scripts" / "gate-check.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


is_human = _load_gate_check().is_human


def load_policy(path: Path) -> dict:
    try:
        import yaml
    except ImportError:  # pragma: no cover
        sys.exit("signoff-check: PyYAML is required")
    if not path.is_file():
        sys.exit(f"signoff-check: {path} not found — the sign-off policy is the policy")
    return yaml.safe_load(path.read_text()) or {}


# --------------------------------------------------------------------------
# Policy validation — pure.
# --------------------------------------------------------------------------

def _validate_scope(name: str, scope: dict, *, requires_key: str) -> list[str]:
    violations: list[str] = []
    for field in ("owner", "granted_by", "default_if_unanswered", "sla_hours",
                  "escalates_after_sla"):
        if scope.get(field) in (None, ""):
            violations.append(f"{name}: missing `{field}`")

    enforced_by = scope.get("enforced_by") or []
    if "signoff_check" not in enforced_by:
        violations.append(f"{name}: `enforced_by` does not list `signoff_check`: {enforced_by!r}")

    owner = str(scope.get("owner") or "")
    owner_tokens = {
        t.strip().lower().removeprefix("role:")
        for t in owner.replace("+", " ").split()
    }
    role_hit = owner_tokens & AGENT_ROLES
    if role_hit:
        violations.append(
            f"{name}: `owner` names agent role(s) {sorted(role_hit)} — no agent "
            f"role may satisfy a client sign-off"
        )

    requires = scope.get(requires_key)
    if not requires:
        violations.append(f"{name}: `{requires_key}` is empty or missing")

    return violations


def validate_structure(policy: dict) -> list[str]:
    violations: list[str] = []

    signoffs = policy.get("signoffs")
    if not signoffs:
        violations.append("policy declares no `signoffs`")
    else:
        for name, scope in signoffs.items():
            violations.extend(
                _validate_scope(f"signoffs.{name}", scope or {}, requires_key="evidence_required")
            )

    change_request = policy.get("change_request")
    if not change_request:
        violations.append("policy declares no `change_request`")
    else:
        violations.extend(
            _validate_scope("change_request", change_request, requires_key="requires")
        )

    if not policy.get("not_gated"):
        violations.append("policy declares no `not_gated` — what this gate leaves alone must be stated")

    if not policy.get("limits"):
        violations.append("policy declares no `limits`")

    return violations


# --------------------------------------------------------------------------
# Classification — pure. Labels and label-event history in, a state out.
# --------------------------------------------------------------------------

def _last_actor_for_label(events: list[dict], label: str) -> str | None:
    """The actor of the most recent `labeled` event that applied `label`.

    None if the label is present on the issue but no such event can be
    found — the label-events API can be incomplete or paginated oddly, and
    a state this cannot determine must never be treated as if it could.
    """
    matches = [e for e in events if e.get("label") == label]
    if not matches:
        return None
    matches.sort(key=lambda e: e.get("created_at") or "")
    return matches[-1].get("actor")


def classify(
    labels: list[str],
    events: list[dict],
    *,
    human_check: Callable[[str], bool] = is_human,
) -> tuple[str, str]:
    """(state, detail) for one item, given its current labels and label
    event history. Pure — no network, fully covered by fixtures."""
    if CHANGE_REQUESTED_LABEL in labels:
        return STATE_CHANGE_REQUESTED, f"`{CHANGE_REQUESTED_LABEL}` is present"

    if APPROVED_LABEL in labels:
        actor = _last_actor_for_label(events, APPROVED_LABEL)
        if actor is None:
            return (
                STATE_UNDETERMINED,
                f"`{APPROVED_LABEL}` is present but no labeling event names "
                f"who applied it",
            )
        if not human_check(actor):
            return (
                STATE_UNSIGNED,
                f"`{APPROVED_LABEL}` was applied by `{actor}`, a bot actor — "
                f"rejected, sign-off must be a person's decision",
            )
        return STATE_SIGNED, f"`{APPROVED_LABEL}` applied by `{actor}`"

    return STATE_UNSIGNED, f"neither `{APPROVED_LABEL}` nor `{CHANGE_REQUESTED_LABEL}` is present"


# --------------------------------------------------------------------------
# The world — gh, isolated so tests never call it.
# --------------------------------------------------------------------------

def gh(args: list[str]) -> str:
    return subprocess.run(
        ["gh", *args], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout


def fetch_issue_labels(issue: int) -> list[str]:
    data = json.loads(gh(["issue", "view", str(issue), "--json", "labels"]))
    return [lbl["name"] for lbl in data.get("labels", [])]


def fetch_label_events(issue: int) -> list[dict]:
    """Every `labeled` event on the issue: {label, actor, created_at}."""
    repo = gh(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"]).strip()
    raw = gh([
        "api", "--paginate", f"repos/{repo}/issues/{issue}/events",
        "--jq", '.[] | select(.event == "labeled") | '
                '{label: .label.name, actor: .actor.login, created_at: .created_at}',
    ])
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--policy", type=Path, default=SIGNOFF_POLICY)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--validate-policy", action="store_true")
    mode.add_argument("--classify", action="store_true")
    parser.add_argument("--issue", type=int)
    parser.add_argument("--scope", choices=["story", "sprint", "release"])
    args = parser.parse_args(argv)

    if args.classify:
        if args.issue is None or args.scope is None:
            parser.error("--classify requires --issue and --scope")
        policy = load_policy(args.policy)
        if args.scope not in (policy.get("signoffs") or {}):
            sys.exit(f"signoff-check: {args.policy} declares no signoffs.{args.scope}")
        labels = fetch_issue_labels(args.issue)
        events = fetch_label_events(args.issue)
        state, detail = classify(labels, events)
        print(f"#{args.issue} ({args.scope}): {state} — {detail}")
        return 0 if state == STATE_SIGNED else 1

    # Default action: validate the policy file itself.
    policy = load_policy(args.policy)
    violations = validate_structure(policy)
    if violations:
        for v in violations:
            print(f"FAIL: {v}", file=sys.stderr)
        print(f"\n{len(violations)} violation(s) in {args.policy}", file=sys.stderr)
        return 1

    print(f"OK: {args.policy} is valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
