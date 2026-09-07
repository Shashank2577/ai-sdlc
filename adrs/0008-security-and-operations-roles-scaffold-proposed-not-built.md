# ADR-0008: Add security (veto) and operations (advisory) roles — scaffold proposed here, built by a developer story

**Status:** proposed
**Work item:** Shashank2577/ai-sdlc#211
**Requirement:** REQ-002, REQ-009

## Context

Eight role packs exist. Every merged PR is reviewed for correctness by QA
and, for critical work, by a human governance gate. **Nothing reviews a
change for security** — credential handling, injection surface, dependency
risk, permission widening, secret exposure — even though this system holds
credentials, mints tokens, runs arbitrary agent sessions on runners, and
publishes a public site. Nothing owns what happens after a merge either:
whether a deploy is safe to promote, whether a rollback plan is real, what
a failure in `prod` means. `policies/environments.yaml` declares a rollback
owner and a human-reviewer rule, but nobody's charter is to judge whether
either is true for a specific change.

`awslabs/aidlc-workflows` names fourteen roles for a human-gated 33-stage
flow, including `aidlc-devsecops-agent`, `aidlc-compliance-agent`,
`aidlc-operations-agent`, and `aidlc-pipeline-deploy-agent`. This ADR
credits that roster as the prior art for "security and operations should
have named owners" without adopting its scale — see Option B.

This is a structural decision, not a code review: it sets a new role's
credential tier, decides whether its write scope can be narrower than the
roles it reviews, and — for security specifically — creates a verdict
label the system is not yet wired to enforce. It also crosses the
architect pack's own write scope: building the packs means writing
`role-packs/security/**` and `role-packs/operations/**`, and registering
them means writing `requirements/coverage.yaml`. `role-packs/architect/charter.md`
is explicit that this pack does not write another role's pack, "not even
the scaffold for the thing you just decided" — the scaffold belongs in
this ADR's Consequences, built by a developer session dispatched against a
work item that links back here. `role-packs/architect/pack.yaml` itself was
built exactly that way, under `Agent-Role: developer`
(commit 3fddd3e), as was `role-packs/delivery-lead/` (commit d04c52f, whose
message states it followed the same pattern). This ADR follows that
precedent rather than breaking it a third time.

## Options considered

### Option A: Do nothing — leave the gap as prose in this ADR

- **Cost:** Zero packs to build or maintain. But the gap this ADR exists
  to close is exactly the one #211 names: a vulnerability is caught by
  luck, not by a role whose job is to look for it. Every future PR keeps
  shipping with no security lens and no owner for deploy/rollback
  judgment.
- **Consequence:** REQ-002's role roster and REQ-009's veto model both stay
  incomplete on the one dimension this programme has explicitly flagged as
  a real hole rather than a missing box on a chart.

### Option B: Adopt `awslabs/aidlc-workflows`'s roster wholesale (14 roles, including 4 that split this ADR's two concerns further)

- **Cost:** At minimum four new packs
  (`devsecops`, `compliance`, `operations`, `pipeline-deploy`) instead of
  two, each needing its own budget, write scope, credential-tier decision,
  and escalation ladder — roughly double the packs for the same two
  concerns this ADR addresses, plus the coordination overhead of deciding
  which of two-to-four overlapping charters a given finding belongs to.
- **Consequence:** This repo has already paid for this mistake once —
  `requirements/coverage.yaml`'s own `roles_built` check (#185) exists
  because unexercised capability reads as completeness. A 14-role roster
  sized for a human-gated 33-stage flow, most of it never dispatched here,
  repeats that pattern at four times the scale for these two concerns
  alone.

### Option C: Two new roles — `security` (binding veto, unenforced pending a devops story) and `operations` (advisory report, no gate) — recommended

- **Cost:** Two packs to build and maintain (~55-turn, $4 budget each per
  the drafted `policy.yaml`, priced between QA's review budget and the
  developer's implementation budget). Security's veto label carries no
  structural enforcement until a separate devops story wires a
  `security-gate.sh`/`security-verdict.sh` pair the way QA's works — that
  is real, admitted cost, not hidden in this ADR. Both packs must declare a
  credential tier and a write scope narrower than what they review, which
  is itself a decision worth recording (see below).
- **Consequence:** The two concerns #211 names — nothing reviews for
  security, nothing owns post-merge deploy judgment — get a named owner
  each, at the minimum roster size that does it, with the enforcement gap
  stated rather than claimed.

Within Option C, two further decisions this ADR is recording:

- **Security's credential tier is `FOUNDRY_DEV_TOKEN`, the same tier as
  developer/QA/PM/architect — not a wider one.** A role reviewing
  credential handling must not itself hold the widest credential in the
  system; that would invert the point of having it. The asymmetry this
  role needs is expressed in write scope, not token scope: security's
  `write_scope.allow` is `role-packs/security/**` only — narrower than
  every role it reviews, including QA's (which at least owns `tests/**`).
  Findings leave the system as labels, comments, and new bug issues —
  tracker writes, not file writes — because there is nothing this role
  needs to commit to prove a finding; a cited file:line is the evidence.
- **Security gets a QA-shaped verdict label; operations gets a report,
  not a second unenforced gate.** #211 asks for a veto "like QA's" for
  security specifically, not for operations. Giving operations its own
  `ops:go`/`ops:no-go` label with no enforcement behind it either would be
  two unenforced gates instead of one honestly-stated one — the same
  completeness-by-appearance failure Option B commits at a different
  layer. Operations instead posts a readiness report (ready /
  not-ready-because-X / named gap) on the work item, which is a narrower
  claim it can actually back today.

## Recommendation

Recommend C: it closes both named gaps at the minimum roster size, prices
the real cost of the unenforced veto instead of hiding it, and keeps
security's own write scope narrower than the credentials and code it
reviews — which the alternative of building it here, in a pack whose write
scope already includes `role-packs/security/**`-adjacent reach, would have
made harder to argue honestly.

## Decision

**Decided:** pending — this ADR proposes Option C; `adrs/` is
CODEOWNERS-routed to a human architect, who decides on merge by editing
this section (`Status: accepted`, `Decided by:`, `Date:`) rather than by
prose elsewhere.

## Consequences

If Option C is accepted, two follow-up work items exist so the scaffold
lands without this ADR's author writing outside its own pack:

1. **A developer story** to create `role-packs/security/**` and
   `role-packs/operations/**` (`pack.yaml`, `charter.md`, `policy.yaml`,
   `tools.yaml`, `skills/`, `templates/`) and add both to
   `requirements/coverage.yaml`'s `policy.roles.expected`, so
   `roles_built` reports honestly against 10 roles instead of silently
   staying green at 8/8. A complete, compiler-validated draft of every
   file — verified against `compiler/compile-pack.py --check` for both
   `claude-code` and `codex`, matching the shape Option C commits to
   above — is attached as a patch on that story, ready to apply rather
   than re-derived from this ADR's prose. Link: Shashank2577/ai-sdlc#215.
2. **A devops story** to give `security:rejected` the same structural
   enforcement `qa:rejected` has (`security-gate.sh` as a required status
   check, a close-guard reopening a closure carrying `security:rejected`,
   the same pattern `scripts/qa-gate.sh` / `scripts/qa-verdict.sh` set).
   Until it lands, `security:rejected` is a documented,
   binding-by-convention recommendation a human merging the PR can see and
   can still override — the security pack's own `charter.md` and
   `policy.yaml` say so explicitly rather than claiming the veto exists.
   Link: Shashank2577/ai-sdlc#216.

Neither follow-up widens an existing role's credential or write scope;
each pack declares its own `token_secret` (`FOUNDRY_DEV_TOKEN`, this
pack's tier) and the dispatcher resolves it with no role→secret table to
edit, per ADR-0001.
