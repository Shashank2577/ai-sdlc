# Operating the system

Everything here is a real command against this repository.

## Dispatch a work item to an agent

```sh
gh workflow run dispatch.yml -f issue=18 -f role=developer
```

Two preconditions, both of which fail loudly rather than quietly:

- **The issue is labelled `status:ready`.** This is the prompt-injection guard,
  not paperwork. The issue body goes verbatim into a session that holds write
  credentials, and on a public repo anyone can open an issue — but only someone
  with write access can apply a label. So the only untrusted text an agent ever
  reads is text a maintainer approved.
- **A harness credential exists.** `CLAUDE_CODE_OAUTH_TOKEN` (from
  `claude setup-token`, works with a Claude Code subscription) or
  `ANTHROPIC_API_KEY`. If both are set, the API key wins.

The session comments on the issue, moves it to `status:in-progress`, works on a
`story/FDY-<n>-<slug>` branch, opens a PR, and reports the outcome and the
spend either way.

## Budgets

Per role, in `role-packs/<role>/policy.yaml`. Changing one is a reviewed PR
against the pack, not a workflow edit.

| Line | Enforcement |
|---|---|
| `turns` | hard stop (`--max-turns`) |
| `wall_clock_minutes` | hard stop (runner timeout) |
| `tokens` | measured after the fact; a breach escalates and costs a retry |
| `max_retries` | dispatch refuses to start once the ladder is spent |

Spend is posted to the work item on **every** session, not only on breach. A
cost metric you only see when something goes wrong is not a metric.

## When something escalates

An escalation is a decision, not a transcript. Every one has: goal, attempts,
blocker, and three costed options with a recommendation.

They arrive as a comment plus the `needs-human` label, from one of:

- a failed or cancelled session,
- a budget breach,
- a spent retry budget (the dispatcher refuses to start — override for a single
  run with `ignore_retry_ceiling: true`),
- three QA rejections on one item,
- an item sitting `status:blocked` for more than 24 hours.

Answer by picking an option and acting. Removing `needs-human` without a reply
is how the ladder loses its meaning.

## The QA veto

`qa:rejected` blocks closure, and it is enforced twice because there are two
ways a rejected story can close:

- a PR merging with `Closes #N` — the `qa-gate` required check fails;
- someone closing the issue by hand — the close guard reopens it.

Overruling QA is possible and deliberate: remove the label. That takes write
access, so it is a human decision recorded in the issue's event history.

## The assignment loop

Runs hourly. Dispatches `status:ready` items with exactly one `role:*` label,
up to the WIP limit in `role-packs/orchestrator/policy.yaml`.

```sh
python3 scripts/assign.py --dry-run     # what would it do right now
```

When nothing is eligible it says nothing at all — no comment, no notification.
A loop that reports "nothing to do" every hour gets muted, and then it is not
there when it says something real. The run log still records every decision.

## Reading the state

```sh
python3 dashboards/standup.py --out site   # who did what, from events
python3 dashboards/build.py   --out site   # REQ -> commits -> merged PRs
python3 scripts/sync-project.py --project 2 --owner Shashank2577 --dry-run
```

Published automatically on every push to `main`, plus daily at 06:10 UTC.

## What still needs a human

These are setup actions no agent can perform, and the system says so rather
than pretending otherwise:

- **Harness credential** — `claude setup-token`, then
  `gh secret set CLAUDE_CODE_OAUTH_TOKEN`.
- **`ORCHESTRATOR_TOKEN`** — a PAT with `actions:write`. GitHub does not let a
  run authenticated with `GITHUB_TOKEN` start another workflow; that rule is
  what stops loops triggering themselves forever.
- **`PROJECT_TOKEN`** — a PAT with `project` scope, so the board sync can
  write. `GITHUB_TOKEN` cannot.
- **Bot identities** — `foundry-dev-bot`, `foundry-qa-bot`,
  `foundry-orchestrator-bot` do not exist yet, so commits are attributed by the
  `Agent-Role:` trailer rather than cryptographically.
