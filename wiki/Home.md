# Foundry

An AI-native software delivery org that is building itself, in public, through
its own process.

Product, architecture, development and QA are run by agents coordinated only
through the tracker. Humans act at decision gates — approve, choose between
costed options — never as free-text supervisors.

## The three rules that do most of the work

1. **Agents coordinate only through work items.** No hidden context. A human
   reading the board sees exactly what every agent sees.
2. **Every action leaves an artifact** — a commit with trailers, a PR, a
   verdict label, a published report. If it did not produce an artifact, it
   did not happen.
3. **Humans decide, agents execute.** Approvals are buttons and reviews.

## Start here

- **[[Operating-the-System]]** — how to dispatch work, what the budgets do,
  what to do when something escalates. Read this one first if you have to run
  the thing today.
- **[[Roles]]** — who does what, what each role may and may not touch.
- **[[Requirements]]** — every REQ and whether it is actually traced to merged
  code.
- **[[Conventions]]** — branches, commit trailers, the label state machine.

## How to check any claim on this wiki

Nothing here is asserted on trust. Open any merged PR and read the commit
trailers; open the traceability matrix and see which requirements really made
it to `main`. Where something is not done, the pages say so rather than
rounding up — the gaps are listed, not hidden.
