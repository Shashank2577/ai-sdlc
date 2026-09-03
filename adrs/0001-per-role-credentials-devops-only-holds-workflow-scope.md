# ADR-0001: Per-role credentials; only DevOps holds `workflow` scope

**Status:** accepted
**Work item:** Shashank2577/foundry-program#42
**Requirement:** REQ-012, REQ-002

## Context

Issue #38 needed a push to `.github/workflows/**` and failed: the default
`GITHUB_TOKEN` cannot write that path. The obvious fix — hand every
dispatched session the one credential that can (`FOUNDRY_TOKEN`, carrying
`repo` + `workflow` + `project`) — was rejected in #42 for two reasons: it
widens every role's reach to unblock one, and it contradicts PRD §3, which
names `.github/workflows/` and `infra/` as DevOps's write scope, not
Developer's. At the time, `role-packs/developer/policy.yaml` allowed
`.github/workflows/**` under the comment "DevOps-adjacent; cross-reviewed" —
a rationalisation, not a boundary.

## Options considered

### Option A: One shared credential, scoped to the union of all roles' needs

- **Cost:** Zero new secrets to provision. But every dispatched session,
  regardless of role, carries `workflow` scope — a developer or QA session
  compromised or misdirected can rewrite the CI checks and dispatcher that
  govern it.
- **Consequence:** Least-privilege (REQ-012) is unenforceable; scope lives
  in prose comments, not in what the token can actually do.

### Option B: Per-role credentials, declared in each pack

- **Cost:** Four secrets to provision instead of one
  (`FOUNDRY_DEV_TOKEN`, `FOUNDRY_DEVOPS_TOKEN`, `FOUNDRY_TOKEN`,
  `GITHUB_TOKEN` fallback); the dispatcher resolves `identity.token_secret`
  per pack instead of hardcoding one. Roles at the same privilege level
  share a secret, so this is not one secret per role.
- **Consequence:** A role's write scope is enforced by what its credential
  can push, not only by policy prose. `.github/workflows/**` and `infra/**`
  move to `role-packs/devops/`, the only pack whose token carries
  `workflow` scope and which cannot merge or approve a PR.

## Recommendation

Recommend B: the credential boundary is the only one a required check
cannot be edited around, because the check is exactly what a wider
credential could edit.

## Decision

**Decided:** Option B
**Decided by:** human (issue #42), implemented in PR #43
**Date:** 2026-09-02 (reconstructed from PR #43's merge commit timestamp;
not stated explicitly in the artefacts)

`.github/workflows/**` and `infra/**` denied to the developer pack;
`FOUNDRY_DEVOPS_TOKEN` (`repo` + `workflow`) given only to `role-packs/devops/`.
The PR that implemented this also relabelled 21 prior commits' provenance:
under the corrected model, every past commit touching
`.github/workflows/` should have carried `Agent-Role: devops`, not
`developer`.

## Consequences

Adding a role never means widening an existing role's token — a new
`pack.yaml` just declares `identity.token_secret`, and the dispatcher reads
it with no role→secret table to edit. A pack whose declared secret is not
configured falls back to `GITHUB_TOKEN` with a loud warning rather than a
silent grant. Any future pack that needs `.github/workflows/` or `infra/`
write access is a decision on the scale of this one, not a policy-file
edit.
