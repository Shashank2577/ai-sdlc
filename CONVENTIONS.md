# Conventions

These rules are enforced by the DoD check (from P0-1 onward). Before
that, they are followed by hand and back-linked.

## Branches

`story/FDY-<issue#>-<slug>` — e.g. `story/FDY-2-dod-check`. Bugs use
`bug/FDY-<issue#>-<slug>`.

## Commit trailers

Every commit on a PR branch carries four trailers:

```
Work-Item: Shashank2577/foundry-program#<issue>
Requirement: REQ-0XX            # comma-separated list allowed
Agent-Role: <orchestrator|pm|architect|developer|qa|devops|techwriter|human>
Harness: <claude-code/x.y|codex/x.y|manual|...>
```

Pre-automation (Stage 0) commits use `Agent-Role: human` and
`Harness: manual`. That is honest provenance, not a gap.

## Labels

`status:*` is the workflow state machine. `qa:approved` / `qa:rejected`
are QA verdicts; a story cannot close while `qa:rejected` is present.
`needs-human` means a structured escalation is waiting for a decision.

## Definition of Done

`policies/dod.yaml` is the policy of record. The enforced subset is
implemented by `scripts/dod-check.sh`, a required status check on
`main`. If the policy and the script disagree, the policy file wins
and the script gets a bug issue.
