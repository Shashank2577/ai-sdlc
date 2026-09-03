# ADR-0004: The approval gate scopes to write capability, not to path mentions

**Status:** accepted
**Work item:** Shashank2577/foundry-program#101
**Requirement:** REQ-007, REQ-012

## Context

`policies/gates.yaml`'s critical-work rules (`touches_governance`,
`changes_requirements`, etc.) matched on whether a story's text named a
protected path, e.g. `.github/workflows/`. Measured across all 53 issues in
the repo at the time, this held 41 (77%) for human approval.
`touches_governance` alone fired on 50%, because this repo's stories
routinely *name* `.github/workflows/` or `policies/` without proposing to
change them — it is a workflow-and-policy repo, so those strings are
everywhere. A `role:developer` story mentioning `.github/workflows/` was
held even though the developer pack denies that path and its token lacks
`workflow` scope (ADR-0001) — a gate on a change that cannot happen. The
policy's own header had predicted this: "a gate on everything is a gate
nobody reads — and a gate nobody reads is worse than no gate, since it
launders whatever passes through it."

## Options considered

### Option A: Keep text/substring matching on protected path names

- **Cost:** Ships as-is; no further work. Ongoing cost is the 77% hold
  rate — real approvals get lost in volume, and a human reviewing gate
  activity habituates to rubber-stamping because most of what they see is
  a story that could never have made the change in the first place.
- **Consequence:** The gate's signal-to-noise ratio stays bad indefinitely;
  PRD §7's "few gates, all visual, each with an SLA" is undermined by
  "few" not holding in practice.

### Option B: Scope each `guards_paths` rule to fire only when the story's role could actually write one of those paths, per that role's own `write_scope`

- **Cost:** The gate check must resolve each role's `write_scope` at
  evaluation time and stay conservative on unknowns — no role label, an
  unrecognised role, two role labels, or an unreadable pack must all still
  count as capable, or the gate becomes bypassable by omitting a label.
  This shipped twice before it was right: the first attempt classified the
  entire backlog as critical (see PR #46's "my first version...").
- **Consequence:** The gate holds only work that could actually touch a
  guarded path. Measured result: 41/53 (77%) -> 34/53 (64%), leaving
  `pipeline_role` and `governance_role` (both meant to hold every time) as
  the largest categories.

## Recommendation

Recommend B: it keeps the gate meaningful without loosening what it
actually protects — the residual holds are exactly the two roles (devops,
delivery-lead) that PRD §13 says should always be held.

## Decision

**Decided:** Option B
**Decided by:** human operator, 2026-09-03 (PR #102, decision 2)
**Date:** 2026-09-03

Rules carrying `guards_paths` now fire only when the story's role's own
`write_scope` reaches one of those paths — the same boundary the credential
model (ADR-0001) already uses, checked through the same code rather than a
second, independently-drifting copy of it. Conservative-on-unknowns is
explicit policy, not an incidental default: an unrefined or ambiguously
labelled story is exactly when least is known, and scoping must not become
a way past the gate for exactly that case.

## Consequences

Any new `critical_when` rule added to `policies/gates.yaml` in future is
expected to carry `guards_paths` and go through this same capability check,
not a bare text match — a rule that skips it reintroduces the 77% noise
problem this ADR exists to fix. `scripts/test_gate_check.py`'s
`test_every_guarded_path_names_a_real_scope_pattern` and
`test_a_pack_cannot_reach_its_own_gate_through_write_capability` are the
enforcement; a change to `gates.yaml` that fails either is reverting this
decision, not extending it.
