# foundry-program

An AI-native software delivery org that is building itself, in public, through its own process.

Every issue, commit, QA verdict and sign-off in this repo is produced by the system this repo contains. The audit trail is the demo. You don't have to take the claim on trust — open any merged PR and read the commit trailers.

**Live board:** https://github.com/users/Shashank2577/projects/2
**Design (PRD v0):** [prds/ai-native-sdlc-blueprint.md](prds/ai-native-sdlc-blueprint.md)
**Requirements:** [requirements/index.md](requirements/index.md)

## The premise

Most agentic coding demos show one agent writing code. This repo is testing something harder: a whole delivery org — product, architecture, development, QA, DevOps — run by agents, coordinated only through the tracker, with humans acting at decision gates. Three rules do most of the work:

1. Agents coordinate only through work items. No hidden context. A human reading the board sees exactly what every agent sees.
2. Every action leaves an artifact: a commit with trailers, a PR, a verdict label, a published report. If it didn't produce an artifact, it didn't happen.
3. Humans decide, agents execute. Approvals are buttons and PR reviews, never free-text supervision.

Full design, including swappable trackers (GitHub Projects / Jira) and swappable harnesses (Claude Code / Codex / DeepSeek), is in the PRD.

## How to verify the claim

- Pick any merged PR. Commits carry `Work-Item:`, `Requirement:`, `Agent-Role:` and `Harness:` trailers. `Agent-Role: human` means a person did it by hand — Stage 0 seeding is labeled as exactly that.
- `requirements/index.md` maps every REQ to a PRD section. Once P0-5 lands, a generated traceability matrix computes REQ → merged PR → release from those trailers. Generated, never hand-written.
- The Definition of Done is a file (`policies/dod.yaml`) enforced by a required status check. Nothing merges on a promise.

## Running the dispatcher

`.github/workflows/dispatch.yml` turns a work item into a headless agent session. Actions → **Dispatch** → Run workflow, then give it an issue number, a role (`developer` or `qa`) and a turn budget. Or from a terminal:

```sh
gh workflow run dispatch.yml -f issue=3 -f role=developer -f max_turns=30
```

Two things have to be true first, and the workflow fails loudly rather than quietly if they aren't:

- **The issue is labelled `status:ready`.** This is the prompt-injection guard, not paperwork. The issue body goes verbatim into a session holding write credentials, and on a public repo anyone can open an issue — but only someone with write access can apply a label. So the only untrusted text an agent ever reads is text a maintainer approved.
- **A harness credential exists** — repository secret `ANTHROPIC_API_KEY`, or `CLAUDE_CODE_OAUTH_TOKEN` for Pro/Max (`claude setup-token`). If both are set, the API key wins.

The session announces itself on the issue, moves it to `status:in-progress`, and reports back either way. On failure, cancellation or a budget breach it hands the item back as `status:ready` + `needs-human` with a structured note — goal, attempts, blocker, costed options A/B/C — so the human gets a decision, not a transcript.

### Budgets

Budgets live in `role-packs/<role>/policy.yaml`, not in the workflow, so changing one is a reviewed PR against the pack:

```yaml
budgets:
  turns: 30
  tokens: 400000
  wall_clock_minutes: 45
  max_retries: 2
  on_breach: escalate
```

Turns and wall clock are hard stops enforced by the runner — a budget an agent can talk itself past is not a budget. Tokens are measured after the fact from the session's execution log and posted to the work item every run, breach or not; cost is a first-class, per-story, visible metric, not something you find out about at the end of the month. Going over does not kill a session, it escalates one, which costs the work item a retry.

`max_retries` is the escalation ladder's last rung. The dispatcher counts how many sessions this work item has already burned — from its own session-end comments, so an agent cannot reset it — and refuses to start once the budget is spent, escalating with the three failures attached instead. `ignore_retry_ceiling: true` overrides it for one run.

## The assignment loop

`.github/workflows/orchestrate.yml` runs hourly, reads the board, and dispatches whatever fits under the WIP limit. Rules live in `role-packs/orchestrator/policy.yaml`:

```yaml
wip:
  limit: 3
  per_role: { developer: 3, qa: 2 }
routing:
  prefix: "role:"          # role:developer / role:qa labels
  supported: [developer, qa]
```

An item is dispatched when it is open, `status:ready`, carries exactly one supported `role:*` label, and is not `needs-human`, `status:blocked` or `qa:rejected`. Anything else is skipped with a reason in the run log. An item with no role label is never guessed at — that is an unfinished refinement, not a developer story.

Three is deliberately low. The bottleneck here is review, not agents: every extra branch in flight ages against `main`, competes for the same reviewer, and raises the odds two sessions touch the same file. Agents being idle costs nothing.

When nothing is eligible the loop **says nothing** — no comment, no issue, no notification. A loop that reports "nothing to do" every hour gets muted, and then it is not there when it says something real. The run log still records every decision.

Arming it needs a PAT: GitHub does not let a run authenticated with `GITHUB_TOKEN` start another workflow, which is what stops loops like this triggering themselves forever. Save a token with `actions:write` + `issues:read` as `ORCHESTRATOR_TOKEN`. Without it the loop still runs and still publishes its plan, in dry-run mode, and says why.

```sh
python3 scripts/assign.py --dry-run     # what would it do right now
```

## Status

Phase 0: proving the spine. Eight stories on the board. Self-hosting starts the moment P0-1 (the DoD check) merges — from that PR onward, every change to this system is machine-gated by the system. The one honest asterisk: the P0-1 PR itself is the last ungoverned change, because the gate has to exist before it can gate anything. It does gate its own PR, though. Check the workflow run on PR #1.

What I don't know yet: whether the escalation ladder fires often enough to be useful or so often it's noise, and what a story actually costs in tokens end to end. Both get measured here rather than estimated.

## Roadmap

Phase 0 proves a story can flow requirement → merge with agents doing the work. Phase 1 adds the full role set and autonomous sprint ceremonies. Phase 2 adds the client-facing layer (transcript → PRD, estimation with confidence bands, demo packages). Phase 3 adds the Jira adapter and a second harness with cross-harness review. Details in PRD §15.

## License

MIT.
