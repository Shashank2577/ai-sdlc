# ADR-0009: A required check runs its enforcing script from `main`, never from the pull request's own merge ref

**Status:** accepted
**Work item:** Shashank2577/ai-sdlc#225
**Requirement:** REQ-005, REQ-007, REQ-012

## Context

`actions/checkout@v4` with no `ref:` on a `pull_request` trigger checks out
the merge ref, which carries the PR's own changes. `dod-check.yml` and
`qa-gate.yml` — the only two required status checks on `main`
(`dod`, `qa-gate`, per branch protection) — ran `scripts/dod-check.sh` and
`scripts/qa-gate.sh` straight off that checkout. A PR that weakened either
script was graded by its own weakened copy: flagged P1 by
`chatgpt-codex-connector` on #10 and #13 on day one, neither thread
answered, and reproduced live on #189 ("#189 modifies `dod-check.sh`
itself, so it runs its own version" — observed and not recognised as the
same hole).

`approval-gate.yml`'s actual enforcement (`gate`, `story-scope-check`)
triggers on `issues: labeled`, which always runs from the default branch —
it was never exposed to this. `unit-tests.yml` is not a required check
(confirmed against live branch protection), so nothing it runs decides a
merge; weakening a script and its own test together is an ordinary code
review problem there, not this one. The hole is exactly the two required
checks: they alone execute a PR-supplied script and use its exit code to
decide whether that same PR can merge.

## Options considered

### Option A: Check out `main` for the whole job, judge the PR's diff from the API instead of local git

- **Cost:** `dod-check.sh` walks `BASE_SHA..HEAD_SHA` with `git log`/
  `git rev-list` against local history for the trailer check — losing the
  merge-ref checkout means re-deriving that from `gh api` calls per commit,
  rewriting logic that already works.
- **Consequence:** Larger diff, more surface for the rewrite itself to be
  wrong, for a job that already has the commit range available in its
  history — fetch-depth 0 pulls every branch, `main` included.

### Option B: Keep the existing checkout (merge ref, `fetch-depth: 0`, so `BASE_SHA..HEAD_SHA` still resolves locally); before running the check, overwrite the working copy of the script with the version read from `origin/main`

- **Cost:** One extra step per job: `git show origin/main:scripts/<x>.sh >
  $RUNNER_TEMP/<x>.sh`, then run that path instead of the in-tree one. Both
  scripts already take everything else they need (PR number, SHAs) from env
  vars and the `gh` CLI, not from their own path, so nothing else moves.
- **Consequence:** The script that decides the merge is always the one a
  human already reviewed on `main`. A PR editing `scripts/dod-check.sh` or
  `scripts/qa-gate.sh` cannot change what judges it, no matter what it
  changes locally — only a merge to `main` can do that, which is exactly
  the review gate this system already relies on everywhere else.

## Recommendation

Recommend B: it isolates the fix to "which copy of the script runs" and
leaves the parts of these jobs that already work — commit-range walking,
`gh` calls, the required-check names branch protection already points
at — untouched. Rewriting the diff-reading logic (Option A) to avoid a
merge-ref checkout would touch more surface for no addition to the
guarantee: the merge ref is safe to keep so long as the *script* on it is
never trusted to grade itself.

This is deliberately narrower than "stop checking out the merge ref
anywhere." `dod-check-tests` and `qa-enforcement-tests` — the jobs a PR
changing these scripts uses to prove the change works — already run their
own copy of the script from the merge ref, and already are not required
checks: they are not contexts branch protection names, so they cannot
decide a merge no matter what they report. That is already the split this
issue asks for ("tests of the check... in a job that does not decide the
merge"); it did not need building, only confirming.

## Decision

**Decided:** Option B
**Decided by:** devops session, implemented in PR (this one), closing #225
**Date:** 2026-09-08

`dod-check.yml`'s `dod` job and `qa-gate.yml`'s `qa-gate` job each gained
one step, immediately after checkout, that reads their script from
`origin/main` into `$RUNNER_TEMP` and runs that path instead of the
in-tree copy. `approval-gate.yml`'s `gate` and `story-scope-check` jobs
were not touched — they already run from `issues: labeled`, which checks
out the default branch by construction, so there was no merge-ref exposure
to close. `unit-tests.yml` was not touched — it is not a required check,
so nothing it runs decides a merge; if it is ever made required, whatever
script it uses to grade a PR against itself would need this same
treatment, but that is a decision for whoever makes it required, not this
one.

`touches_governance` (`policies/gates.yaml`) was verified, not changed:
`scripts/gate-check.py --classify --issue 225` returns
`CRITICAL / touches_governance: mentions '.github/workflows/'` against
this issue's own text, and `scoping: write_capability` (ADR-0004) still
resolves `role:devops` as able to write `.github/workflows/**`, so the
rule fires for exactly the role that can make this kind of change.
`scripts/test_gate_check.py` already asserts both the match and the
scoping in code; nothing here needed a new assertion.

The hole was demonstrated closed on this PR: a throwaway commit weakened
`scripts/dod-check.sh` to always exit 0 and paired it with a commit
deliberately missing a required trailer. The `dod` check still failed —
it read the unweakened script from `origin/main`, not the weakened one on
the branch — before the demonstration commits were reverted. See the PR
description for the run link.

## Consequences

Any workflow that becomes a required status check in future and executes
a script this repository's own history controls (not a third-party
action) is expected to pin that script to `origin/main` the same way, or
it reopens exactly this hole under a different file name. A reviewer
adding a new required check should ask this ADR's question — "does this
job run a script the PR under review could have changed?" — before
merging the branch-protection change that makes it required.

`dod-check.sh` and `qa-gate.sh` still read `BASE_SHA`/`HEAD_SHA`/`PR_NUMBER`
from the environment and reach the PR's actual diff through `git log`
against the merge ref's history and `gh pr view`/`gh issue view` — pinning
the script's own source does not, and must not, change what it inspects,
only what code does the inspecting.
