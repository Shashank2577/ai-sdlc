# Role packs

Harness-neutral agent role definitions per PRD §3. Each pack is a
directory:

```
role-packs/<role>/
├── pack.yaml       # identity, harness compatibility, model prefs
├── charter.md      # mission, boundaries, escalation rules
├── skills/         # markdown skills, one concern each
├── tools.yaml      # allowed tools, shell allow/deny, MCP servers
├── policy.yaml     # budgets, forbidden actions, HITL triggers
└── templates/      # comment and document templates the role uses
```

`compiler/compile-pack.py` renders a pack for a target harness; CI checks
that every committed pack still compiles.

| Role | Pack | Story |
|---|---|---|
| Developer | `developer/` | P0-3 (#4) |
| QA | `qa/` | P0-4 (#5) |
| Orchestrator | — | P0-8 (#9) |

The remaining roles from PRD §3 (PM/BA, architect, DevOps, tech writer,
delivery manager) arrive in Phase 1. Each pack lands through a tracked
story, built by the process it will then participate in.

**Pack changes are PRs.** The team's training is reviewed and versioned
like any other change — that is the point of keeping roles in files rather
than in prompts.
