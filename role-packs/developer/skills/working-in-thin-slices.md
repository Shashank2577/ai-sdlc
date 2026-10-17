# Skill — working in thin slices

Writing three hundred lines before anything runs spends the budget on
finding which part broke. A "while I was here" cleanup gives QA a second
change to review.

**The loop:**
1. Make the smallest testable piece of the work item.
2. Run its test, then anything else it could affect.
3. Commit it, with all four trailers.
4. Build the next slice on top; don't restart.

If you've written about 100 lines without running anything, stop and run
something.

**Riskiest slice first.** A dead end found in the first quarter of the
budget is a cheap escalation. Found in the last quarter, it's a session that
ends with nothing.

**Scope is the work item.** Do what the acceptance criteria ask, nothing
more. Note anything else you spot as a comment on the work item, not as a
change in this PR. Stay inside `policy.yaml:write_scope`. No abstraction for
a single use, no option nobody asked for.

**Every commit stays shippable.** Tests pass after each one. Add before you
remove, in separate commits, so either can be reverted. One thing per
commit.

**One work item, one PR.** If the prompt says the item already has an open
PR, check out its branch and keep going there. Never open a second PR for
the same item.

_Adapted from `incremental-implementation`,
[addyosmani/agent-skills](https://github.com/addyosmani/agent-skills),
MIT License, Copyright (c) 2025 Addy Osmani._
