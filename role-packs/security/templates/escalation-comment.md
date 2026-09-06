### Escalation — human decision required

**Role:** security · **Session:** <run URL> · **Spend:** <turns/tokens/wall-clock used of budget>

**Goal**

Reach a security verdict on #<n> (PR #<p>).

**Why no verdict was reached**

<One of: confirming the finding needs access this role should not be given
to confirm it · the exposure is severe enough to need immediate human
attention rather than a normal review cycle · a fix would require editing
another role's write scope. Be specific about which.>

**Attempts**

1. <What was checked.> → <What was found, or why it couldn't be confirmed.>
2. <What was different about the second attempt.> → <How it failed.>

**Blocker**

<The one thing in the way, with the command and output that demonstrates
it — without executing anything against live credentials or systems.>

**Options**

- **A — <action>** (<cost, who does it>). <Consequence.>
- **B — <action>** (<cost>). <Consequence.>
- **C — <action, often "hold the PR until a human confirms">** (<cost>).
  <Consequence.>

**To act on this**

Reply with the option letter, then remove the `needs-human` label — that
label is what holds the item, and nothing reads this comment. The reply is
the record; removing the label is what releases the work.

**Recommendation:** <A|B|C>, because <one sentence>.

**Partial findings**

<Anything verified before the blocker, so the next session does not repeat
it.>

<!--
Escalating is not a third verdict. If a verdict is reachable, reach it.
Never widen this role's own credential or write scope to resolve a
blocker — that is exactly the failure mode this pack exists to prevent.
-->
