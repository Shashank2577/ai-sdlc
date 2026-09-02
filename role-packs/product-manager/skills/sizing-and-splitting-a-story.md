# Sizing and splitting a story

This is the skill that decides whether the story you write actually gets
built, or bounces back to you two sessions from now unrefined in a new
disguise.

## The evidence

Look at how this repo's dispatched sessions actually went, not at theory.
The sessions that succeeded had issue bodies naming the exact function,
file, and test class to touch. The sessions that failed had issue bodies
describing an outcome — "make the dashboard faster", "improve error
handling" — and left the developer session to first figure out what you
meant, then build it, inside the same turn budget.

An outcome is not a story. A story names the thing to change.

## What "named concretely" means

Before you write acceptance criteria, you should be able to answer, from
the requirement and the codebase, not from guessing:

- Which file or files does this touch? Say the path.
- Which function, class, or component is the surface of the change?
- Is there an existing test file this extends, or does one need to be
  created — and where?
- What does "done" look like as a command someone can run — a test suite,
  a script, a specific check?

If you cannot answer these after reading the relevant code and the PRD,
that is information, not a blocker to push through. Either investigate
until you can, or say explicitly in the story that this part is
unconfirmed and flag it as a risk — never paper over the gap with vaguer
language.

## Splitting an epic

An epic becomes multiple stories when it has more than one of: a distinct
file/module touched, a distinct test surface, or a natural point where one
piece could ship and be reviewed without the rest. Split along those lines,
not by guessing at "sprint-sized chunks."

Signs a "story" is still an epic wearing a smaller costume:

- Its acceptance criteria span more than one component with no shared
  function or file between them.
- You had to write "and" three times in the user-story line to cover
  everything it does.
- No single estimate size (S/M/L) feels honest — it keeps wanting to be
  "M, unless X, in which case L."

When in doubt, split smaller. A developer session can always be told the
next story picks up where this one left off; it cannot un-guess a story
that was too big to fit its own turn budget.

## Sizing

Use the estimate categories already in use in this repo (S/M/L, or a
three-point estimate once ensemble estimation is wired up). Ground the
estimate in the same concreteness this skill asks for elsewhere: an item
that names one file and one test class is smaller than one that touches
three subsystems, regardless of how the words describing it feel.

State the estimate's basis in one line on the story — "M: one new
role-pack directory, mirrors two existing packs" — so a human or an
estimator session can sanity-check the number against the reasoning, not
just the number.
