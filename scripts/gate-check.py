#!/usr/bin/env python3
"""Enforce the dispatch-approval gate: critical work waits for a person.

`policies/gates.yaml` says which stories are critical. This decides
whether a given story matches, and — when an agent has just marked a
critical story `status:ready` — hands it back for a human.

Approval is not a label an agent can forge. It is the identity of whoever
applied `status:ready`: the `issues: labeled` event payload carries the
sender, so a person applying it *is* the approval. Same idea as the
dispatcher's `status:ready` guard, one level further in.

    gate-check.py --classify --issue 42          # print the verdict, change nothing
    gate-check.py --enforce --issue 42 --actor github-actions[bot]

Exit 0 always for --classify. For --enforce, 0 whether or not it acted;
this runs on every label change and a gate that fails the build on a
routine edit is a gate people switch off.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GATES = REPO_ROOT / "policies" / "gates.yaml"
READY = "status:ready"
UNREFINED = "status:needs-refinement"


def load_gate(path: Path = GATES) -> dict:
    try:
        import yaml
    except ImportError:  # pragma: no cover
        sys.exit("gate-check: PyYAML is required")
    if not path.is_file():
        sys.exit(f"gate-check: {path} not found — the gate policy is the policy")
    gate = (yaml.safe_load(path.read_text()) or {}).get("gates", {}).get(
        "dispatch_approval")
    if not gate:
        sys.exit("gate-check: gates.dispatch_approval missing from the policy")
    return gate


# --------------------------------------------------------------------------
# Classification — pure. Text and labels in, matched rules out.
# --------------------------------------------------------------------------

def _pattern(needle: str) -> re.Pattern:
    """Word-boundary match, not substring.

    Substring matching made every story critical: `PAT` matches inside
    "dis**pat**ch", and this repo's vocabulary is full of the words the
    rules look for. A gate that catches everything is the gate nobody
    reads — which is what the policy's own `limits` paragraph warned
    about, and I shipped it anyway.

    Three shapes, because one rule cannot cover them:

    - path-like (`policies/`) matches literally; a slash is already a
      boundary;
    - a trailing underscore (`FOUNDRY_`) is a prefix, so it matches the
      rest of the identifier — `\b` fails there, since `_D` is not a
      boundary;
    - everything else gets `\b` on both ends.
    """
    needle = needle.strip()
    if "/" in needle:
        return re.compile(re.escape(needle), re.IGNORECASE)
    if needle.endswith("_"):
        return re.compile(rf"\b{re.escape(needle)}\w*", re.IGNORECASE)
    return re.compile(rf"\b{re.escape(needle)}\b", re.IGNORECASE)


def matched_rules(title: str, body: str, labels: list[str], gate: dict) -> list[dict]:
    """Every critical rule this story trips. Empty means routine.

    Returns all matches rather than the first, because the comment should
    tell a human every reason it was held, not just one.
    """
    haystack = f"{title}\n{body}"
    out = []
    for rule in gate.get("critical_when", []):
        match = rule.get("match") or {}
        hit = None
        if "label" in match and match["label"] in labels:
            hit = f"label `{match['label']}`"
        else:
            for needle in match.get("text_any", []):
                if _pattern(needle).search(haystack):
                    hit = f"mentions `{needle.strip()}`"
                    break
        if hit:
            out.append({"rule": rule.get("rule", "?"), "hit": hit,
                        "because": " ".join((rule.get("because") or "").split())})
    return out


def is_human(actor: str) -> bool:
    """A bot cannot satisfy a gate whose owner is `human`.

    GitHub App actors end in `[bot]`; `github-actions` is the workflow
    identity. Anything else is treated as a person — erring toward
    "approved" here would defeat the gate, so the list is deliberately of
    known non-humans rather than known humans.
    """
    name = (actor or "").strip().lower()
    return bool(name) and not (name.endswith("[bot]") or name in
                               {"github-actions", "dependabot", "copilot"})


# --------------------------------------------------------------------------
# The world
# --------------------------------------------------------------------------

def gh(args: list[str]) -> str:
    return subprocess.run(["gh", *args], cwd=REPO_ROOT, check=True,
                          capture_output=True, text=True).stdout


def read_issue(number: int) -> dict:
    return json.loads(gh(["issue", "view", str(number),
                          "--json", "number,title,body,labels,state"]))


def render_held(number: int, matches: list[dict], gate: dict) -> str:
    lines = [
        "### Held for approval",
        "",
        f"`{READY}` was applied by an agent, and the dispatch-approval gate "
        f"classifies this story as **critical**. It is back on "
        f"`{UNREFINED}` with `needs-human`, so nothing will dispatch it "
        f"until a person moves it to `{READY}` themselves.",
        "",
        "**Why it was held**",
        "",
    ]
    for m in matches:
        lines.append(f"- **{m['rule']}** — {m['hit']}. {m['because']}")
    lines += [
        "",
        f"**To approve:** apply `{READY}` yourself. The gate reads who "
        "applied the label, so there is nothing else to do and nothing an "
        "agent can do in your place.",
        "",
        f"**If you do nothing:** it stays on `{UNREFINED}` "
        f"(default per `policies/gates.yaml`, SLA {gate.get('sla_hours', '?')}h).",
        "",
        "_Classification reads issue text and labels, so it is best-effort. "
        "If this is a false positive, approving it is the fix — and worth "
        "saying so on the issue, because the rule that caught it may be too "
        "broad._",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--issue", type=int, required=True)
    ap.add_argument("--actor", default="")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--classify", action="store_true")
    mode.add_argument("--enforce", action="store_true")
    args = ap.parse_args()

    gate = load_gate()
    issue = read_issue(args.issue)
    labels = [lbl["name"] for lbl in issue.get("labels", [])]
    matches = matched_rules(issue.get("title", ""), issue.get("body") or "",
                            labels, gate)

    if args.classify:
        print(f"#{args.issue}: {'CRITICAL' if matches else 'routine'}")
        for m in matches:
            print(f"  {m['rule']}: {m['hit']}")
        return 0

    # --enforce
    if READY not in labels:
        print(f"#{args.issue} is not {READY}. Nothing to gate.")
        return 0
    if is_human(args.actor):
        print(f"#{args.issue}: {READY} applied by `{args.actor}`, a person. Approved.")
        return 0
    if not matches:
        print(f"#{args.issue}: routine, applied by `{args.actor}`. "
              "No approval needed, nothing to do.")
        return 0

    # Scratch goes to RUNNER_TEMP, never the checkout.
    note = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "gate-note.md"
    note.write_text(render_held(args.issue, matches, gate))
    gh(["issue", "comment", str(args.issue), "--body-file", str(note)])
    gh(["issue", "edit", str(args.issue), "--remove-label", READY,
        "--add-label", UNREFINED, "--add-label", "needs-human"])
    print(f"#{args.issue}: held for approval — "
          f"{', '.join(m['rule'] for m in matches)} (applied by `{args.actor}`).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
