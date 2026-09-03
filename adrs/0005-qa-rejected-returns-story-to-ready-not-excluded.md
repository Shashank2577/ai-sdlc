# ADR-0005: `qa:rejected` returns a story to dispatch eligibility rather than excluding it

**Status:** accepted
**Work item:** Shashank2577/foundry-program#75, #79
**Requirement:** REQ-009, REQ-002

## Context

`role-packs/orchestrator/policy.yaml` listed `qa:rejected` in
`eligibility.exclude_labels`, so the loop would never dispatch a story
carrying that label — a deadlock, since QA's own charter says "do not fix
the code, reject with specifics; a developer session fixes it," but nothing
could dispatch that developer session while the rejecting label was still
attached. Issue #75 names its own origin honestly: "I wrote the exclusion
and the comment justifying it... and never built the 'back through its
author' half." Issue #52 was stuck in exactly this state: rejected, PR
unmergeable, no path back through the loop. A second defect (#79) compounded
it: even with `qa:rejected` removed from `exclude_labels`, QA dispatch
itself used a fixed `eligibility.require_labels: [status:ready]` for every
role, so QA — dispatchable from `status:in-review` per the dispatcher's own
guard — could still never be *planned* by the loop, only run by hand.

## Options considered

### Option A: Keep `qa:rejected` in `exclude_labels`; build a separate re-dispatch path for rejected work

- **Cost:** A second dispatch mechanism to design, build and keep in sync
  with the primary one — eligibility rules would exist in two places for
  what is otherwise one state machine.
- **Consequence:** `qa:rejected` continues to double as both "blocks
  closure" (its real job, already enforced structurally by
  `scripts/qa-gate.sh` and `qa-verdict.sh close-guard`) and "blocks
  dispatch" (redundant with the first, and the thing actually causing the
  deadlock).

### Option B: Drop `qa:rejected` from `exclude_labels`; fix eligibility to read each role's own `dispatchable_from`

- **Cost:** `scripts/assign.py` eligibility moves from one fixed
  `require_labels` to reading `role-packs/<role>/pack.yaml`'s
  `dispatchable_from` per role — more moving parts, but the same
  declaration the dispatcher's own guard already reads via the compiler, so
  no new source of truth is introduced.
- **Consequence:** A rejected story can be replanned once a human moves it
  back to `status:ready` (the state gate that actually governs
  redispatch — a rejected item cannot reach `status:ready` on its own).
  `qa:rejected` stops doing double duty; it blocks closure only, which is
  where it was already enforced structurally.

## Recommendation

Recommend B: the state gate (`status:ready`, human-applied per ADR-0004's
approval model) already governs when a rejected story can be replanned;
having the label do the same job too was redundant and, on top of it, the
thing actually deadlocking #52.

## Decision

**Decided:** Option B
**Decided by:** architect/developer session, implemented in PR #81, closing
#79
**Date:** 2026-09-02 (reconstructed from PR #81's merge commit timestamp)

PR #81 states this plainly as a judgment call beyond the issue's own
Gherkin scenarios — none of which names `qa:rejected` directly: "This is an
interpretive call... but it's what made `scripts/test_assign.py:
test_qa_rejected_blocks` need inverting per the issue's own note, and it's
consistent with the issue's `#52 -> missing status:ready` diagnostic
(confirmed live, see Evidence)."

## Consequences

`qa:rejected` now means exactly one thing — the PR cannot merge and the
issue cannot close — enforced in two places
(`scripts/qa-gate.sh`, `scripts/qa-verdict.sh`), not three. Eligibility for
dispatch is read per-role from `dispatchable_from` rather than one
repo-wide `require_labels` default, which is the mechanism any future role
with a non-standard dispatch state (like QA's `status:in-review`) is
expected to use instead of adding another special case to
`scripts/assign.py`.
