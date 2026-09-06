# ADR-0008: The learning loop detects recurring corrections with fixed mechanical matchers over tracker records, and promotion is always a human-approved proposal, never a write

**Status:** proposed
**Work item:** Shashank2577/ai-sdlc#212
**Requirement:** REQ-013

## Context

`scripts/memory.py` and `refs/notes/foundry` are the store half of REQ-013.
This work item's own framing ("it has never been used for it... none has
ever been written at all") is out of date against the record:
`requirements/coverage.yaml`'s REQ-013 entry shows the write path fired for
real when dispatching #169 escalated and wrote a note to commit `773451c`,
and a second dispatch of that same issue then read the note back out of
its own assembled prompt — the store is built *and* exercised, not built
and unexercised. Getting that
distinction right is itself the discipline this ADR is about: asserting a
state without checking the record is one of the three correction patterns
#212 names. The gap that is real is the loop — turning a
correction that keeps recurring into a rule the *next* session inherits
without a person repeating it — has never been built. The cost of that gap
is on the record, not hypothetical: the acceptance-criteria write-scope
violation this ADR's own work item cites was corrected seven times (#52,
#103, #114, #116, #121, #159, #173) before anyone encoded it as
`scripts/check-story-scope.py` (#168/#172) — six of those seven correction
comments, plus the retro/root-cause and coverage-drift patterns #212 also
names, are sitting in issue and PR comments this repo already has.

Prior art: `awslabs/aidlc-workflows` names this "human corrections become
persistent behavioural rules," running inside an interactive session where
a human corrects an agent in the moment and the correction is captured
immediately. This repo's loop cannot do that — it dispatches disposable
sessions against a tracker, so a correction is never witnessed live; it can
only be reconstructed after the fact from what the tracker already
recorded. That is a different problem wearing the same name (the issue
body is explicit about this), so this ADR takes the idea — repetition is
the signal that promotes a correction to a rule — not the mechanism.

The decision that cannot be deferred to whichever PR builds this first is
**how a "recurring correction" gets identified from the record, and what
happens once it is**. Get the first part wrong (a scheme that can't tell a
coincidence from a pattern, or can't be pinned to a test) and the loop
either misses the next #168 or manufactures superstition. Get the second
part wrong (anything that writes a rule without a human approving it) and
an agent has quietly rewritten its own instructions — the exact thing
least-privilege (ADR-0001, ADR-0004) exists to prevent.

## Options considered

### Option A: Fixed, per-pattern mechanical matchers over tracker records, counted and thresholded, output as a proposal issue

A script (developer-owned, `scripts/**`) reuses `retro.py`'s existing
event collectors — closed-issue comments, escalation comments
(`### Escalation`), QA-rejection labels, PR review comments, amended
acceptance-criteria diffs — and runs a small, explicit set of matchers
against them, one per known correction shape (write-scope-violation,
root-cause-asserted-unverified, coverage-notes-drift, ...). Each matcher is
a pure function: comment/label text in, a pattern key out, exactly like
`check-story-scope.py`'s `analyze()` is a pure function from a story body
to a verdict. Occurrences of the same pattern key are counted across the
whole record (not just one retro window, since the seven write-scope
occurrences span #52 through #173 — months, not one window). At or above
threshold, the script opens a proposal — a new issue, not a commit —
naming the pattern, linking every occurrence, and suggesting a landing
artifact.

- **Cost:** One matcher per correction shape someone has already noticed
  and named, plus the collector plumbing (mostly reused from `retro.py`).
  Small, bounded build; no ongoing spend beyond retro's existing `gh` calls.
  Known-shape corrections not yet given a matcher are invisible to the loop
  until a person adds one — the same recall-for-precision trade
  `check-story-scope.py`'s own docstring already makes and defends.
- **Consequence:** The count is mechanically derived from the record, so it
  reproduces. Acceptance criterion #2 — reproduce the seven write-scope
  occurrences as a test case — becomes an ordinary fixed-input unit test
  (a list of seven comment bodies in, pattern key + count 7 out), the same
  shape as `scripts/test_check_story_scope.py`. New correction shapes need
  a person to notice one and write a matcher; that person is already the
  one who'd otherwise write the promoted rule by hand, so the marginal
  cost is small.

### Option B: An agent session reads all comments each retro window and semantically clusters similar corrections, proposing promotion for any cluster over a size threshold

- **Cost:** Recurring LLM spend every retro window, growing with issue
  history since there is no cheap way to cluster only the new comments
  without re-reading old ones for context. Every clustering run needs a
  human skim to catch confident-sounding false groupings before they reach
  the threshold count.
- **Consequence:** Broader recall — it can notice a recurring correction
  nobody has named yet, which Option A structurally cannot. But "is this
  the same correction as that one" becomes a model's judgement call made
  fresh each run, which directly contradicts the acceptance criterion that
  the count come from the record rather than a judgement call, and a
  nondeterministic clustering cannot be pinned to the fixed seven-comment
  test case #2 requires — the test would assert on a similarity score, not
  a count.

### Option C: No dedicated detector — rely on the existing retro ceremony (`retro.py`) surfacing escalations and closed issues each window, and ask the human reviewing that issue to notice repeats by eye

- **Cost:** Nothing to build.
- **Consequence:** This is the status quo the work item exists to fix,
  restated. `retro.py` already surfaces every escalation and closed issue
  per window, and a human read all seven write-scope escalations without
  the pattern becoming a rule until the eighth was one occurrence past
  seven — the record shows this option's failure mode, not a theory about
  it.

## Recommendation

Recommend A: it is the only option where the "recurring" count is a fact
about the record — checkable, testable, and stable — rather than either a
model's judgement (B) or a person's memory across windows (C, the failure
already on the record).

## Decision

**Decided:** Option A
**Decided by:** _pending human architect review_
**Date:** _pending_

Threshold: **3 independent occurrences** (distinct issues or PRs), not 2.
Two instances of the same correction can still be one correlated cause —
the same author, the same planning session, hitting the same edge twice —
and cannot yet be told apart from coincidence. Three requires the
correction to have been independently re-applied across at least three
separate review passes, which is the point the acceptance criteria
themselves already treat as meaningful: the root-cause-asserted pattern is
listed at three occurrences and named as worth a table row, while "two
occurrences is noise" is stated outright. Three is the documented floor
already in the record, not a round number picked for this ADR.

Promotion is a **proposal**, structurally, not by convention: the detector
opens a tracker issue (mirroring how `retro.py` opens one retro issue per
window — same "observe, don't act" boundary its own docstring states) that
names the pattern, links every occurrence, and suggests a landing artifact
and location. It writes no file and opens no PR. Turning the proposal into
a change still goes through an ordinary role session, a reviewed PR, and
whatever CODEOWNERS routes that path to — the same human-approval path
every other change in this repo takes, not a new gate invented for this
one. This is the same shape ADR-0007 already established for approval:
proven by what a person did (opened/merged a PR), never by the agent's own
assertion that its output is fine to apply.

Landing rule — where a promoted pattern goes, decided by what kind of
correction it is, not by who is available to build it:

| Correction is... | Lands in | Example already in the record |
|---|---|---|
| A mechanically checkable invariant (a path, a label, a required field) | a **check** (new script, or a rule added to an existing one like `check-story-scope.py`), wired into CI or dispatch | the seven write-scope occurrences → #168 |
| Procedural judgement no script can evaluate (verify before asserting, a review habit) | a **skill** in the relevant role pack's `skills/` | the three root-cause occurrences |
| A cross-role rule, budget, or gate definition | `policies/**`, delivery-lead's write scope | the five coverage-notes-drift occurrences, if promoted |

A proposal that fits none of these three is not yet a rule — it stays an
issue, not a document, because a rule with no enforcement point is prose
nobody is bound by.

## Consequences

This commits scripts/** (developer-owned, not this pack's write scope) to
building the detector described above as a follow-up work item, including
the fixed-input test that reproduces the seven write-scope occurrences
(acceptance criterion #2) — that work is out of `adrs/**`/
`role-packs/architect/**`, so it is not done in this PR. `requirements/**`
is product-manager's write scope, not architect's; the REQ-013 coverage
notes should gain a line distinguishing "the store, built and exercised on
#165/#169" from "the loop, decided in ADR-0008, built in <follow-up
issue>" once that follow-up exists — also a separate work item, filed
against product-manager.

Any future correction-detection work inherits the same two constraints
this ADR fixes in place: the count must come from a matcher over the
record, not a model's or a person's judgement call in the moment, and
nothing this loop produces may land as a write without going through the
same reviewed-PR path every other change takes. A detector that instead
opened its own PR and merged it, or wrote directly to a role pack's
`skills/`, would need a new ADR superseding this one, not a quiet
extension of it.
