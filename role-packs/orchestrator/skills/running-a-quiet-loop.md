# Skill — running a quiet loop

## Silence is a feature

This loop runs on a schedule. Most of the time there will be nothing to do,
and the correct output is nothing: no comment, no issue, no label, no
notification.

A loop that posts "checked the board, nothing eligible" every fifteen minutes
teaches everyone to mute it within a day. Then, when it says something that
matters, nobody reads it. The value of a notification is entirely determined
by how often it is worth reading.

The run log is not silence — it should say plainly what was considered and
why nothing was picked, so the decision is auditable. Silence means no
**tracker artifact**: nothing that generates a notification or clutters an
item's history.

## What is worth saying

Only these:

- **A dispatch happened.** The dispatcher posts its own session-start comment
  on the item, so the loop itself does not need to.
- **The board is stuck.** Items sitting `status:ready` across several
  consecutive runs while nothing dispatches. That is a real problem and it is
  invisible from a dashboard, because nothing is red — the loop is simply
  doing nothing, forever, correctly.
- **Every eligible item is missing a role.** Refinement has quietly stopped.
- **The WIP limit is permanently full.** Sessions start and never finish;
  the queue has become a wall.

Notice what those have in common: none of them show up as a failure anywhere
else. That is the bar for speaking.

## Say it once

Before escalating, check whether the last escalation is still open. An
unaddressed `needs-human` is not a reason to post again — the human already
knows, and a second comment adds nothing except noise on an item that is
already flagged.

Repetition is how automation loses credibility. One good comment that stays
unanswered is the human's problem. Six identical comments is yours.

## Idempotence

The loop may run twice in quick succession — a cron overlapping a manual run,
a retried job. Two runs against the same board must reach the same decision
and must not double-dispatch.

Two things make that hold:

- Count in-flight work from `status:in-progress`, which the dispatcher sets,
  not from anything this loop tracks itself.
- The dispatcher's own `concurrency` group is per work item, so a second
  dispatch of the same issue queues behind the first rather than racing it.

Neither is a lock. They are enough for a loop that runs every fifteen minutes
and would not be enough for one that ran every fifteen seconds — which is a
good reason not to run it every fifteen seconds.

## Dry runs

The loop supports a dry run that computes everything and dispatches nothing.
Use it after any change to eligibility or WIP rules, and read the plan before
turning the change loose on a live board. The cost of being wrong here is
several agent sessions on the wrong work.
