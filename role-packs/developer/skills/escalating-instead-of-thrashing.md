# Skill — escalating instead of thrashing

## The failure mode this prevents

An agent hits a wall, retries the same approach with cosmetic variations,
burns its whole budget, and ends the session with no PR, no explanation,
and a work item that looks identical to how it started. The human learns
nothing except that it failed.

Escalation is not giving up. It is converting spent budget into a decision
someone can act on.

## When to stop

Stop immediately, without retrying, when:

- The acceptance criteria contradict each other, or the PRD.
- The change needs a write outside `policy.yaml:write_scope`.
- A credential, permission, or secret is missing.
- The work item is materially larger than its estimate — a story that turns
  out to be three stories.

Stop after **two** failed attempts when:

- The same test keeps failing for the same reason.
- The same command keeps erroring after you have changed the inputs.
- You have rewritten the same file three times and it is not converging.

The rule of thumb: if your third attempt is a variation on the first two
rather than a different idea, you are thrashing. Escalate.

## Budget awareness

Watch the turn budget in your prompt. When roughly a quarter of it is left
and there is no PR yet, decide deliberately: land something small and
correct, or escalate. Do not let the ceiling arrive mid-edit — a session
killed at the limit leaves a half-written branch and no explanation, which
is the worst of both outcomes.

## What an escalation contains

Use `role-packs/developer/templates/escalation-comment.md`. Four parts,
none optional:

1. **Goal** — one sentence, in the work item's terms, not yours.
2. **Attempts** — what you tried and the specific way each failed. Error
   messages, not paraphrases.
3. **Blocker** — the one thing standing in the way, stated so a human can
   verify it independently.
4. **Options** — A, B and C, each with a cost and a consequence. Recommend
   one and say why.

Then apply `needs-human` and end the session.

## Options are the whole point

A human being handed "it didn't work" has to redo your investigation. A
human handed three costed options makes a decision in thirty seconds.

Weak:

> Blocked on the API key. Please advise.

Strong:

> **Blocker:** `ANTHROPIC_API_KEY` is not set on the repository, so the
> dispatcher's preflight fails before any session starts. Verified:
> `gh secret list` returns empty.
>
> **A — add the secret** (~2 min, human). Unblocks this and every future
> dispatch. Recommended: nothing else in the backlog works without it.
>
> **B — run this story with a stubbed harness** (~1h agent). Proves the
> workflow shape but not the integration; the gap moves to QA rather than
> disappearing.
>
> **C — defer to after P0-7** (0 now). Costs nothing today, blocks three
> other stories.

## Never escalate silently

The escalation goes on the **work item**, as a comment, with the label.
Not in a commit message, not in a PR description on a branch nobody opens,
not in the run log. If it is not on the tracker, it did not happen.
