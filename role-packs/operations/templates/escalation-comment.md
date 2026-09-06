### Escalation — human decision required

**Role:** operations · **Session:** <run URL> · **Spend:** <turns/tokens/wall-clock used of budget>

**Goal**

Reach a deploy-readiness judgment on #<n> (PR #<p>).

**Why no judgment was reached**

<One of: the rollback plan's realism cannot be confirmed without access
this role does not have · the change appears to narrow prod's human gate
· the promotion order or environment ladder itself looks wrong, not just
the change under review. Be specific.>

**Attempts**

1. <What was checked, against which environments.yaml entries.> → <What
   was found, or why it couldn't be confirmed.>
2. <What was different about the second attempt.> → <How it failed.>

**Blocker**

<The one thing in the way, with the command and output that demonstrates
it.>

**Options**

- **A — <action>** (<cost, who does it>). <Consequence.>
- **B — <action>** (<cost>). <Consequence.>
- **C — <action, often "hold the promotion until a human confirms">**
  (<cost>). <Consequence.>

**To act on this**

Reply with the option letter, then remove the `needs-human` label — that
label is what holds the item, and nothing reads this comment. The reply is
the record; removing the label is what releases the work.

**Recommendation:** <A|B|C>, because <one sentence>.

**Partial findings**

<Anything verified before the blocker, so the next session does not repeat
it.>

<!--
Escalating is not a substitute for a readiness report. If a judgment is
reachable, reach it. Never dispatch, approve, or run a deploy from this
role — that decision belongs to policies/environments.yaml's named human
reviewer.
-->
