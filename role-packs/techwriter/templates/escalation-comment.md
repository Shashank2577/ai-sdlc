### Escalation — human decision required

**Role:** techwriter · **Session:** <run URL> · **Spend:** <turns/tokens/wall-clock used of budget>

**Goal**

<One sentence. What doc, release note, or demo walkthrough was this session
supposed to produce?>

**Attempts**

1. <What was tried — which trailers/commits/docs you read.> → <What was still missing.>
2. <What was different about the second attempt.> → <What was still missing.>

**Blocker**

<The one thing in the way, stated so a human can verify it independently:
a commit range with missing or malformed trailers, acceptance criteria
that contradict the PRD, or scope that turned out to need a write outside
`docs/`.>

**Options**

- **A — <action>** (<cost: time, who does it>). <Consequence.>
  <Why this is or isn't the recommendation.>
- **B — <action>** (<cost>). <Consequence.>
- **C — <action, often "do nothing / defer">** (<cost>). <Consequence.>

**To act on this**

Reply with the option letter, then remove the `needs-human` label — that
label is what holds the item, and nothing reads this comment. The reply is
the record; removing the label is what releases the work.

**Recommendation:** <A|B|C>, because <one sentence>.

**State left behind**

- Open questions already filed: <list, or "none">
- Any doc or note partially drafted: <what's done, what's missing, and
  which claims in it are trailer-backed vs. still unverified>
- Nothing was deleted, force-pushed, merged, or closed.

<!--
Rules for whoever fills this in:
- Options must be costed and mutually exclusive. Three real choices, not
  one plan and two strawmen.
- "Please advise" is not an option. If you cannot name three, name two and
  say why there is no third.
- Post this on the work item and apply `needs-human`. Nowhere else counts.
-->
