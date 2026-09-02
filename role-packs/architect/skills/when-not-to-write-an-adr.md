# Skill — when not to write an ADR

## The default failure mode is too many, not too few

A missing ADR is visible: someone eventually asks "why is it built this
way?" and there is no answer. A redundant ADR is invisible in the same way
noise is invisible — it just makes the next real one harder to find, until
`adrs/` is a place nobody opens because the signal-to-decision ratio is bad.
Once that happens the mechanism is dead for the change that actually needed
it.

## Ask one question: would reverting this need more than one PR?

If reverting the decision is "revert this commit," it does not need an ADR.
If reverting it means touching multiple components, migrating data, walking
back a convention other code now depends on, or renegotiating something
external (a vendor, a client-facing contract) — that is the shape of thing
`adrs/` exists for.

## Cases that look structural and are not

- **A library swap with one caller.** If the blast radius is one module and
  the PR that makes the change can also revert it, review carries this.
- **A naming or formatting convention.** Put it in `CONVENTIONS.md` or a
  linter config. An ADR is for a decision with competing options and a
  cost; a style choice usually is not.
- **A performance fix with one obviously correct answer.** If there is only
  one reasonable option, there is nothing to record a choice between —
  write the reasoning in the commit or PR body instead.
- **Anything already decided by an existing ADR.** Reference it. Do not
  re-litigate a settled decision by writing a second document that says
  the same thing in different words.

## Cases that look small and are not

- **A dependency addition**, even a small one, if it is the kind every
  future PR in this area will be expected to use. The cost is not the
  install; it is the convention it creates.
- **A change that crosses two roles' write scope** — if shipping it means a
  developer and a devops session both need to act, the coordination itself
  is the thing worth writing down, independent of how simple either side's
  diff is.
- **"We'll just do it this way for now."** Temporary structural decisions
  outlive the sprint that made them more often than not. If it is genuinely
  temporary, say so in the ADR and give it a review trigger, rather than
  skipping the record because it feels provisional.

## If genuinely unsure

Write the one-paragraph version: the decision, the two options, and stop.
A thin ADR that exists costs a reviewer thirty seconds. A structural
decision with no record costs the next person who hits it a full
investigation to reconstruct what you already knew.
