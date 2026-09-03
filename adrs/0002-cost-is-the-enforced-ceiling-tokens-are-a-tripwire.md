# ADR-0002: Cost is the enforced budget ceiling; tokens are a reported, non-breaching tripwire

**Status:** accepted
**Work item:** Shashank2577/foundry-program#23
**Requirement:** REQ-012, REQ-007

## Context

The repo's first live agent dispatch (run 33583977341, issue #22) cost
$0.61 and was reported as a 1,414,300-token, 3.5x budget breach against a
400k-token ceiling. Of those tokens, 1,351,447 (96%) were cache reads —
re-reads of context already paid for once. Fresh tokens were ~63k, well
inside budget. The escalation ladder fired on an accounting artifact, not
on overspend, and its own advice ("read the transcript before spending
again") was unfollowable: the transcript is written to `$RUNNER_TEMP` and
destroyed with the runner, so the run had zero artifacts to read.

## Options considered

### Option A: Keep tokens (including cache reads) as a hard breach line

- **Cost:** Every cache-heavy session — which is most of them, since
  rehydrating a role pack and its charter on each turn is exactly what the
  harness caches — reads as a breach regardless of actual spend. The
  escalation ladder burns a retry on sessions that did nothing wrong.
- **Consequence:** The budget model measures context-window mechanics, not
  the thing the org actually pays for.

### Option B: Cost becomes the enforced ceiling; tokens are reported and flagged, never breach; cache reads excluded from the token count

- **Cost:** Requires the dispatcher to plumb actual per-session cost
  (already available from the harness) into the spend report, and to
  separate cache reads from fresh tokens (input + output + cache writes) in
  the count that's reported.
- **Consequence:** A session is judged on what it actually cost the org.
  Tokens remain visible for diagnosing runaway context growth, but stop
  being a false-positive breach source.

## Recommendation

Recommend B: cost is the number that is actually scarce here (a fixed
dollar ceiling per work item); a token count that's 96% cache reads tells a
reviewer nothing about spend.

## Decision

**Decided:** Option B
**Decided by:** human (issue #23), implemented in PR #24
**Date:** 2026-09-02 (reconstructed from PR #24's merge commit timestamp)

Replaying the same session's real numbers under the new rules: $0.61 of
$5.00, 31 of 60 turns, 63k of 400k fresh tokens — no breach, correctly. The
developer turn budget was also raised 30 -> 60 in the same change, on the
evidence that 31 turns with no branch pushed was a session still reading
code, not one looping.

## Consequences

Every role pack's `policy.yaml` budget model (see
`role-packs/architect/policy.yaml`) now states `cost_usd` as the breaching
ceiling and `tokens` explicitly as a tripwire only ("reported, never a
breach"). Any future budget dimension added to a pack should name, up
front, whether it is enforced or advisory — this decision is the reason
that distinction exists in the budget schema at all.
