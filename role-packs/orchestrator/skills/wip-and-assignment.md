# Skill — WIP limits and assignment

## Count what is real

In flight means `status:in-progress` — the label the *dispatcher* applies
when a session actually starts. Not `status:ready`, not "I am about to
dispatch it", not open PRs.

The distinction matters because the orchestrator must never count its own
intentions. If it did, two runs racing each other would each count the
other's plan and both would dispatch, which is exactly the overrun the limit
exists to prevent.

```sh
gh issue list --state open --label status:in-progress --json number | jq length
```

Slots free = `limit - in_flight`, floored at zero. Dispatch at most that
many. If it is zero, dispatch nothing and stop.

## Why the limit is low

Three feels wrong until you watch it. The bottleneck in this system is not
how fast agents write code — it is how fast a human reviews and merges. Every
extra branch in flight:

- ages against `main` and starts needing rebases,
- competes for the same reviewer,
- and increases the chance two sessions touch the same file.

A queue is visible and cheap. A traffic jam of eight half-finished branches
looks like progress on a dashboard and is worse than having done nothing.

Raising the limit is a PR against `policy.yaml` with a reason, and the reason
has to be about review capacity, not about agents being idle. Agents being
idle is fine. Agents being idle costs nothing.

## Per-role caps

`wip.per_role` caps a single role under the global limit — three developer
sessions is fine, three QA sessions means QA has become the queue. A per-role
cap never raises the global limit; both have to allow a dispatch.

## Deterministic order

Two runs against the same board must make the same decisions. That rules out
anything model-judged.

1. Items with an open PR first — finishing beats starting.
2. Then lowest issue number.

That is the whole rule. If real priority matters, it belongs on the item as a
field a human set, and the rule becomes "read that field" — still
deterministic.

## Never guess a role

An item labelled `status:ready` with no `role:*` label is not a developer
story by default. It is an item somebody marked ready without finishing
refinement.

Skip it and say so. Guessing right nine times out of ten means the tenth
dispatches a QA session at an implementation story and burns a budget for
nothing — and, worse, hides the refinement gap that caused it.

## Dispatch is a request, not a state change

```sh
gh workflow run dispatch.yml -f issue="$n" -f role="$role"
```

That is all. The dispatcher runs its own guard, posts its own session-start
comment, and moves the label. The orchestrator does not move the label
itself, because then the board would show work in progress for a session
that may have failed its guard three seconds later.

Report what you dispatched. Do not report what you expect it to do.
