# ADR-0007: Approval is proven by the identity of who applied the label, never by the label's presence

**Status:** accepted
**Work item:** Shashank2577/foundry-program#45
**Requirement:** REQ-007, REQ-012

## Context

`policies/gates.yaml`'s `dispatch_approval` gate needed a mechanical
definition of "approved to run unsupervised" for critical work. A label
alone (`status:ready`) is not proof of anything: any session with write
access to issues can apply a label, including an agent session — so a gate
that only checks for the label's presence is a gate an agent can satisfy
for itself, which is not a gate.

## Options considered

### Option A: Treat `status:ready` as approval whenever present, regardless of who applied it

- **Cost:** None to build — labels are already read everywhere else in the
  loop this way.
- **Consequence:** Forgeable. Any agent session that can label an issue
  (which dispatch itself requires, for routine work) can self-apply the
  approval label on critical work too, defeating the gate it is supposed to
  pass through.

### Option B: Enforce via the `issues: labeled` event payload's sender — dispatch proceeds only when a human account applied the label; an agent-applied label on a critical rule reverts the story and posts `needs-human`

- **Cost:** Requires a maintained `is_human()` classification — a
  deny-list of non-human actor patterns (`[bot]` suffixes,
  `github-actions`, `dependabot`, `copilot`), erring toward "not a person"
  on anything unrecognised, since erring the other way defeats the gate on
  exactly the case it exists for.
- **Consequence:** Approval is a fact about who took an action GitHub
  itself recorded (the event sender), not a marker a session can assert
  about itself. Same mechanism the dispatcher's `status:ready`
  prompt-injection guard already relies on, applied one level further in.

## Recommendation

Recommend B: it is the only option where "approved" is a fact the gate
observes rather than a claim the gated thing can make about itself.

## Decision

**Decided:** Option B
**Decided by:** architect/developer session, implemented in PR #46, closing
#45
**Date:** 2026-09-02 (reconstructed from PR #46's merge commit timestamp,
`4ed0c48`, in git log — not stated in the PR body itself)

```
bot   + critical  -> HELD — reverted to status:needs-refinement, needs-human, comment names every rule
bot   + routine   -> no action, no comment
human + critical  -> approved (a person applied it)
```

`is_human()` is a deny-list, not an allow-list, and an empty actor is
treated as non-human — both deliberate, since erring toward "approved" on
an unrecognised actor would defeat the gate.

## Consequences

Any future approval-shaped gate in this repo (this ADR's mechanism is
reused, not just precedent, by ADR-0003's `governance_role` rule and
ADR-0004's capability scoping) is expected to check actor identity from the
event payload, not label presence, or it inherits this exact forgeability
gap. `scripts/test_gate_check.py` is where that expectation is checked in
code.
