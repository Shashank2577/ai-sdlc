### Escalation — human decision required

**Role:** qa · **Session:** <run URL> · **Spend:** <turns/tokens/wall-clock used of budget>

**Goal**

Reach a verdict on #<n> (PR #<p>) against its acceptance criteria.

**Why no verdict was reached**

<One of: the criteria are untestable as written · verification needs access
this session does not have · the criteria contradict the PRD. Be specific
about which criterion.>

**Attempts**

1. <What was tried.> → <How it failed. Paste the actual output.>
2. <What was different about the second attempt.> → <How it failed.>

**Blocker**

<The one thing in the way, with the command and output that demonstrates it.>

**Options**

- **A — <action>** (<cost, who does it>). <Consequence.>
- **B — <action>** (<cost>). <Consequence.>
- **C — <action>** (<cost>). <Consequence.>

**Recommendation:** <A|B|C>, because <one sentence>.

**Partial findings**

<Anything verified before the blocker, so the next session does not repeat
it. Criteria already confirmed met, with evidence.>

<!--
Escalating is not a third verdict. If a verdict is reachable, reach it —
"cannot be verified" is a rejection, not an escalation. Escalate only when
the criteria themselves, or the access needed to test them, are the problem.
-->
