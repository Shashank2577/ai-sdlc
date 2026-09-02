### Escalation — the board is stuck

**Role:** orchestrator · **Run:** <run URL>

**Goal**

Keep eligible work moving within the WIP limit.

**Attempts**

<How many consecutive loop runs found nothing to dispatch, and what each run
saw: how many items were `status:ready`, how many had a role, how many slots
were free.>

**Blocker**

<One of:>
- <N items are `status:ready` but none is eligible — <reason per item>.>
- <Every eligible item is missing a `role:*` label; refinement has stopped.>
- <The WIP limit (<n>) has been full for <duration>; sessions start and never
  reach `status:in-review`.>

**Options**

- **A — <action>** (<cost, who does it>). <Consequence.>
- **B — <action>** (<cost>). <Consequence.>
- **C — <action>** (<cost>). <Consequence.>

**To act on this**

Reply with the option letter, then remove the `needs-human` label — that
label is what holds the item, and nothing reads this comment. The reply is
the record; removing the label is what releases the work.

**Recommendation:** <A|B|C>, because <one sentence>.

**Board state**

| | |
|---|---|
| `status:ready` | <n> |
| eligible | <n> |
| in flight | <n> of <limit> |
| `needs-human` | <n> |
| `status:blocked` | <n> |

<!--
This escalation exists because a stuck board is invisible: nothing is red,
no check fails, the dashboard is green, and the loop does nothing forever.

Post it once. If the last escalation on this item is still unanswered, the
human already knows — a second comment adds noise, not information.
-->
