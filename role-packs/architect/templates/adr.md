<!--
ADR template — role-packs/architect. See charter.md "When to write an ADR"
before filling this in; the mechanism is only useful if it stays reserved
for decisions that are actually hard to reverse. See skills/costed-options.md
for what makes a cost defensible instead of decorative.

File as adrs/NNNN-title-in-kebab-case.md, numbered sequentially.
-->

# ADR-NNNN: <decision, stated as a title, not a question>

**Status:** proposed <!-- proposed | accepted | superseded by ADR-NNNN -->
**Work item:** <owner>/<repo>#<issue#>
**Requirement:** REQ-0XX

## Context

<What forces this decision. Why now, and why it cannot be deferred to the
PR that happens to touch this area first. One or two paragraphs — this is
the reason the ADR exists, not a history of the investigation.>

## Options considered

Each option needs a real cost and a real consequence. A "do nothing" option
is welcome here if it is a genuine contender — cost it honestly rather than
writing it to lose.

### Option A: <name>

- **Cost:** <time / money / ops burden / migration pain — name which one
  is actually scarce for this decision, and give a number or a range with
  its assumption stated.>
- **Consequence:** <what becomes true afterward if this is chosen.>

### Option B: <name>

- **Cost:** <...>
- **Consequence:** <...>

<!-- add Option C, D... only if each is a real contender, not padding. -->

## Recommendation

<One sentence naming the tradeoff: which option, and the cost it wins on.
Not "B seems better" — "Recommend B: half the ops burden of A, and the
migration cost is one-time where A's is recurring.">

## Decision

**Decided:** <Option A | Option B | ...>
**Decided by:** <human architect handle>
**Date:** <YYYY-MM-DD>

<One sentence: why the costs favored this option. If the decision differs
from the recommendation above, say what changed the reviewer's weighing.>

## Consequences

<What this commits the org to going forward — the ongoing cost from the
chosen option's cost line, made concrete. Note any follow-up work item this
ADR implies (a scaffold, a migration, a convention update), so it is
traceable rather than left implicit in this document.>
