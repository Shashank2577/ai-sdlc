# Skill — costed options

## A cost is a number or a named quantity, not an adjective

"Option A is simpler" is not a cost. "Option A: two days, no new
dependency, on-call already knows the failure modes" is. PRD §11 gives the
shape to aim for: "Option A: Kafka (cost, ops burden, fit) / Option B: SQS
(…) / recommendation + why." Every option in that pattern answers the same
three questions, so a reviewer can compare them without translating.

## What "cost" means here

Pick whichever is actually scarce for this decision, and say which one you
picked:

- **Build cost** — time, and whose time.
- **Ongoing cost** — a dollar figure, a new service to operate, a
  dependency the org now patches forever.
- **Migration cost** — what has to move, and whether it can move
  incrementally or is all-or-nothing.
- **Reversal cost** — if this is wrong, what does undoing it take. This is
  often the number that actually decides the ADR; a cheap-to-build,
  expensive-to-reverse option is a different bet than the reverse.

A cost that cannot be estimated honestly gets a range and a stated
assumption, not a made-up precise figure. "$400–800/mo at current traffic,
assuming no replication" is a real cost. "$600/mo" with no basis is
decoration wearing a number.

## Every option needs a consequence, not just a cost

The consequence is what becomes true if this option is chosen — the shape
of the system afterward, not the price of getting there. "We now operate a
message broker" is a consequence. "$X/month" is the cost that sits next to
it. Both are required per option; a cost without a consequence tells a
reviewer what it takes to get somewhere without saying where.

## "Do nothing" is a real option, not a throwaway one

When status quo is on the table, cost it honestly: what does it continue to
cost to not decide, and what breaks first if nothing changes. A "do
nothing" option written to obviously lose is not a second option, it is a
recommendation with padding. If it genuinely is the weakest choice, the
honest cost accounting will show that on its own — it does not need help.

## The recommendation is one sentence, and it names the tradeoff

"Recommend B: half the ops burden of A, and the migration cost is one-time
where A's is recurring." Not "B seems better." The sentence should let a
human architect either agree in one read or spot exactly which tradeoff
they weigh differently — that disagreement, stated precisely, is the fast
path to a real decision instead of a re-litigation from zero.
