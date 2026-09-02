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
| Orchestrator | `orchestrator/` | P0-8 (#9) |
| Product Manager | `product-manager/` | P1-1 (#39) |
| DevOps / SRE | `devops/` | P0-17 (#42) |
| Tech Writer | `techwriter/` | P1-5 (#50) |

The remaining roles from PRD §3 (architect, delivery manager) arrive in
Phase 1.

**Each pack declares the credential it is dispatched with**
(`identity.token_secret`). Roles at the same privilege level share one;
`.github/workflows/**` belongs to DevOps alone, so a role that writes code
cannot edit the check that reviews it. A pack that names no credential does
not compile. Each pack lands through a tracked
story, built by the process it will then participate in.

**Pack changes are PRs.** The team's training is reviewed and versioned
like any other change — that is the point of keeping roles in files rather
than in prompts.
