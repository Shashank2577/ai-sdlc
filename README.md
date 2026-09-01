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

## Status

Phase 0: proving the spine. Eight stories on the board. Self-hosting starts the moment P0-1 (the DoD check) merges — from that PR onward, every change to this system is machine-gated by the system. The one honest asterisk: the P0-1 PR itself is the last ungoverned change, because the gate has to exist before it can gate anything. It does gate its own PR, though. Check the workflow run on PR #1.

What I don't know yet: whether the escalation ladder fires often enough to be useful or so often it's noise, and what a story actually costs in tokens end to end. Both get measured here rather than estimated.

## Roadmap

Phase 0 proves a story can flow requirement → merge with agents doing the work. Phase 1 adds the full role set and autonomous sprint ceremonies. Phase 2 adds the client-facing layer (transcript → PRD, estimation with confidence bands, demo packages). Phase 3 adds the Jira adapter and a second harness with cross-harness review. Details in PRD §15.

## License

MIT.
