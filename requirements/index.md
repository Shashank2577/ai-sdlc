# Foundry — Requirement Index (REQ v0)

Provenance: client call 2026-09-01 (this design conversation) + PRD v0 (`ai-native-sdlc-blueprint.md`).
Per Foundry convention, every story, commit trailer, and test maps back to one of these IDs.

| ID | Requirement | PRD § |
|---|---|---|
| REQ-001 | All agent coordination happens through the tracker; every agent action produces a durable, visible artifact. No hidden context, no side channels. | §1 P1–P2 |
| REQ-002 | Roles are harness-neutral packs (skills, tools, policy, templates) with distinct signed bot identities; attribution is cryptographic. | §3 |
| REQ-003 | Harness adapter: Claude Code, Codex, DeepSeek (et al.) interchangeable behind one dispatch contract; single-harness mode fully functional. | §11.2 |
| REQ-004 | Tracker adapter: GitHub Projects ↔ Jira swappable via canonical work-item schema; git remains code-side source of truth either way. | §11.1 |
| REQ-005 | Git-native traceability spine: signed commits, commit trailers (Work-Item, Requirement, Agent-Role, Harness), git notes for metadata, CODEOWNERS routing, protected branches, signed tags as sign-offs. | §4 |
| REQ-006 | All five ceremonies (refinement, planning, standup, review/demo, retro) run autonomously on schedule and each terminates in artifacts. Standups are event-derived, never self-reported. | §5 |
| REQ-007 | Human-in-the-loop = decision gates (approve / choose between costed options), never free-text supervision. Few gates, all visual, each with an SLA and default. | §7 |
| REQ-008 | Client layer: transcript→PRD with provenance-linked REQs, versioned client sign-offs, change requests with impact analysis, Monte Carlo estimation with confidence bands, demo packages, portal. | §6 |
| REQ-009 | QA holds a veto (`qa:rejected` blocks closure); Definition of Done is policy-as-code enforced as a required check; QA reports are published HTML artifacts mapped to requirements. | §8 |
| REQ-010 | Environment ladder preview→dev→staging→prod; production deploys sit behind a human gate (GitHub environment required reviewer); every release ships a rollback plan. | §9 |
| REQ-011 | Visibility layer: boards, generated dashboards (burndown, velocity, cost-per-story), computed traceability matrix (REQ→release, red/green). The program is operable without reading agent transcripts. | §10 |
| REQ-012 | Guardrails: least-privilege per role, per-work-item budgets (tokens/time/retries), escalation ladder (retry → alt approach → alt harness → human), nothing irreversible without a human. | §13 |
| REQ-013 | Persistent engineering memory across ephemeral sessions (git notes + MCP — Seal); retro learnings promote into role packs via reviewed PRs. | §12 |
| REQ-014 | Self-hosting: the system builds itself through itself. POC exit = one full sprint where every story improves the system, flows through the system, and humans touch only gates. | Self-hosting plan |

## Traceability convention

- Branch: `story/FDY-<issue#>-<slug>`
- Commit trailers (required, enforced by DoD check once P0-1 ships):

```
Work-Item: <org>/foundry-program#<n>
Requirement: REQ-0XX
Agent-Role: <role|human>
Harness: <claude-code/x.y|manual>
```

Pre-automation commits (Stage 0) use `Agent-Role: human` and `Harness: manual` — back-linked, not gold-plated.
