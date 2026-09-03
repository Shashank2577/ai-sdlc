# ADR-0003: The governance owner keeps `policies/**` but not other roles' packs

**Status:** accepted
**Work item:** Shashank2577/foundry-program#101
**Requirement:** REQ-007, REQ-012

## Context

`role-packs/delivery-lead/policy.yaml` allowed `write_scope` on both
`policies/**` and `role-packs/**`. The second grant meant the governance
pack could rewrite any other role's (including its own) budget, tool
denials and write scope — which made two of its own `forbidden` entries,
`granting_itself_more_scope` and `change_widens_another_roles_permissions`,
prose rather than enforced scope. This shipped unnoticed (`d04c52f`)
because the CI job that tests it, `approval-gate.yml`, was path-filtered to
exclude `role-packs/**` — the exact directory the bug is about (tracked
separately as #100).

## Options considered

### Option A: Keep `role-packs/**` as delivery-lead's write scope

- **Cost:** None to build — this was already the state. The ongoing cost is
  that governance's own `forbidden` list cannot be trusted: a rule saying a
  pack "must not grant itself more scope" is unenforced if that same pack
  can edit the file the rule lives in.
- **Consequence:** No agent-writable boundary actually constrains the
  governance role. Every other role's scope is only as safe as this one
  pack's judgment, every session.

### Option B: Narrow to `role-packs/delivery-lead/**`; other packs change only via a human-merged PR

- **Cost:** Governance changes to another role's pack become two-step —
  the delivery-lead session proposes, a human merges — instead of one
  agent-authored commit. Matches the scoping already used for `devops`.
- **Consequence:** A permission-widening change becomes visible as a PR a
  person reviews, which is where PRD §13's "nothing an agent does
  unsupervised is irreversible" says it should surface anyway.

### Option C: Remove `policies/**` from delivery-lead entirely

- **Cost:** The gates (`policies/gates.yaml`, `policies/dod.yaml`) would
  have no agent owner and no way to be changed through the loop at all —
  every gate edit becomes a manual, off-loop human commit.
- **Consequence:** Safer in isolation, but reverses the reason a governance
  role pack exists (PRD §13: guardrails need an owner, not just a human
  editing YAML by hand forever).

## Recommendation

Recommend B: it keeps governance's reason to exist (an agent owner for the
gates) while removing the one grant that made its own self-scoping rules
unenforceable. C is the safer static state but undoes the pack's purpose;
A is the status quo the bug report exists to fix.

## Decision

**Decided:** Option B
**Decided by:** human operator, 2026-09-03 (per PR #102, "Two governance
decisions, both settled by the human operator on 2026-09-03")
**Date:** 2026-09-03

`role-packs/delivery-lead/policy.yaml` write scope narrowed to
`policies/**` and `role-packs/delivery-lead/**`, nothing wider — matching
how `devops` is scoped to its own pack. The `policies/**` exception is kept
deliberately, and is asserted safe under two conditions that are now tests
rather than prose: every `role:delivery-lead` story is critical by its
label alone (new `governance_role` gate rule, see ADR-0004), and the pack's
`shell.allow` omits both merge and approve commands so it structurally
cannot self-approve.

## Consequences

Any future widening of `role-packs/delivery-lead/**` toward another pack's
directory is, by this ADR, the kind of change that needs its own ADR and
explicit human sign-off — not a policy tweak folded into an unrelated
story. `scripts/test_gate_check.py` now asserts
`test_no_pack_may_write_another_packs_directory` as the general form, so
this specific failure mode cannot recur in a different pack without a test
failing first. `approval-gate.yml`'s `pull_request.paths` filter was
widened to include `role-packs/**` in the same change, so this class of bug
running green and unnoticed cannot repeat undetected.
