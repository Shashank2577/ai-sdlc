# Skill — changing a gate

## The three questions

Every workflow change answers these in the PR body. A reviewer should not
have to ask any of them.

**1. What can now happen that could not before?**

Name the capability, not the diff. "Added `workflow` scope to the developer
credential" is a diff. "A developer session can now edit the check that
reviews it" is the capability, and it is the sentence that gets the change
rejected — correctly.

**2. What still stops the bad version of that?**

If the answer is "the charter says not to", there is no control. The charter
is a prompt; prompts are advisory. The controls that hold are:

- branch protection with admin enforcement
- required status checks
- token scope
- environment required-reviewers

Everything else is documentation. That distinction has cost this repo real
sessions: a 55-entry Bash allowlist was called least-privilege while branch
protection was doing all the actual work.

**3. How would you notice if it broke?**

A workflow that fails loudly is fine. One that silently stops enforcing is
how a gate becomes theatre. This repo has an example worth remembering: the
retry ceiling grepped session-end comments for the string
`session (failed|was cancelled)`, which the code never wrote. It reported
zero prior failures across three failed sessions for weeks, and nothing was
red the whole time.

If a check can pass by not running, say how you would find out.

## Never weaken a gate to unblock a story

The pressure is always the same shape: a session is blocked, the gate is in
the way, widening the gate is one line. Do not.

The order is:

1. Should this role be able to do that at all? Often the answer is no and
   the work belongs to a different role.
2. If yes, can a narrower credential scoped to that role do it? Prefer a
   second secret over a wider first one.
3. Only then, should the existing control change — and that is a decision
   with a named owner, not a side effect of unblocking a story.

## Test what you cannot run

Workflows triggered by `issues:`, `schedule:` or `push:` do not run on a
pull request, so their logic cannot be verified by the PR that introduces
them. Two things follow.

Put the logic in a script and test the script. `scripts/qa-verdict.sh` and
`scripts/test-qa-enforcement.sh` are the pattern: a stub `gh` on `PATH`, and
assertions on the calls made rather than on prose. Negative assertions carry
the most weight — a run that should change nothing must make no calls at
all, because a scheduled job that comments every time gets muted, and then
it is not there when it says something real.

Then say plainly in Evidence that the trigger itself is unverified until it
is on `main`. An honest "this cannot run until merged" beats a confident
paragraph implying otherwise.

## `actionlint` is not a formality

Run it with `shellcheck` wired in:

```sh
actionlint -shellcheck="$(which shellcheck)" .github/workflows/*.yml
```

Every `run:` block is shell. Real findings from this repo, all of which
would have failed at runtime on a step nobody was watching:

- `timeout-minutes: ${{ steps.x.outputs.y }}` — step outputs are strings;
  needs `fromJSON()`.
- A step referencing `$COST_USD` without it in that step's `env:`, which
  would have rendered a blank budget in every comment.
- `sed 's/$/`/'` flagged as an unexpanded expression, and correctly so.

## Scratch files belong in `$RUNNER_TEMP`

Never the checkout. Anything left in the work tree is something a session
can commit by accident, and the diff arrives in a PR nobody expected it in.
