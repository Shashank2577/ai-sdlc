# ADR-0011: One GitHub App with per-role tokens replaces the three PATs, and a required check enforces who may write what

**Status:** proposed
**Work item:** Shashank2577/ai-sdlc#322
**Requirement:** REQ-012, REQ-002, REQ-005

## Context

ADR-0001 kept workflow edits to devops by handing devops a different
credential: `FOUNDRY_DEVOPS_TOKEN` (`repo` + `workflow`), `FOUNDRY_DEV_TOKEN`
(`repo`) for the other writers, and `FOUNDRY_TOKEN` (`repo` + `workflow` +
`project`) for the orchestrator. All three are classic PATs minted from the
owner's own account. Five weeks of running on them (#322, from the
2026-10-17 gap analysis §7) show four costs that ADR-0001 did not price:

1. **Every agent action is recorded as the owner.** ADR-0007's `is_human()`
   reads the event sender. When an agent labels an issue with the owner's
   PAT, the sender is `Shashank2577`, so the human-only gates pass for the
   agent. That is the forgery ADR-0007 exists to stop, re-entered by the
   credential.
2. **Every new product needs the PATs to reach it.** Two of the eight manual
   steps in the onboarding path (#323) are about credential reach.
3. **`write_scope` is enforced by nothing.** A role's
   `policy.yaml:write_scope` is prompt prose. A token cannot express "may
   write `adrs/**` but not `scripts/**`", and no check reads a PR's diff
   against the role that produced it. Only the workflow boundary has teeth,
   because only that one maps onto a token scope.
4. **Three long-lived, account-wide secrets.** A classic PAT reaches every
   repository the owner can, with no expiry beyond what the owner
   remembers to set.

## Options considered

### Option A: Keep the three PATs (do nothing)

- **Cost:** none to build. Every new product still needs PAT reach, by hand.
  The owner keeps rotating three account-wide tokens.
- **Consequence:** costs 1–4 above remain. `is_human()` stays defeated
  whenever an agent acts, which makes every human gate in the repo advisory.

### Option B: One GitHub App per role (ten Apps, matching `identity.git_user`)

- **Cost:** ten Apps to create, ten private keys to store, ten installations
  per product. That is the "20 tokens" onboarding the gap analysis found
  nobody will do.
- **Consequence:** distinct per-role actors and signed commits (REQ-002's
  "cryptographic attribution"). But onboarding gets worse, not better, and
  `write_scope` is still unenforced, because a per-role App has the same
  path-blind permissions as a per-role PAT.

### Option C: One GitHub App (`foundry[bot]`), a per-role token minted at dispatch, and a required scope check

- **Cost:**
  - one App, created from a checked-in manifest (`infra/github-app/`), with
    its private key in one secret and its client ID in one variable;
  - a token-minting step in each workflow that writes as an agent;
  - a new required check, `scope` (`scripts/check-write-scope.py`).
  - **The board needs a workaround.** Apps cannot write *user-owned* Projects
    v2, because no App permission covers them; only organization projects
    have one. On a user account, board sync keeps one optional classic PAT
    with only the `project` scope. On an organization the App covers it.
- **Consequence:** three credential boundaries replace one.
  1. **Token, per role.** `actions/create-github-app-token` mints an
     installation token with only the permissions the role's pack declares
     (`pack.yaml:identity.github_permissions`). Only devops's declaration
     includes `workflows: write`. GitHub itself refuses a non-devops push
     that touches `.github/workflows/**`, exactly as it refuses one from
     `FOUNDRY_DEV_TOKEN` today. ADR-0001's guarantee is kept, not traded.
  2. **Path, per role.** The `scope` check reads every commit's
     `Agent-Role` trailer. It confirms that role was actually dispatched on
     the work item, using the dispatch record `dispatch.yml` posts as
     `github-actions[bot]` and the dispatch run it points to. It then
     fails any changed file outside that role's `write_scope`, deny before
     allow. A `.github/workflows/**` change must come from a devops dispatch
     even if a token were ever over-granted.
  3. **Actor.** The App acts as `foundry[bot]`, so `is_human()` is true only
     for people again, with no change to `gate-check.py`.

  Tokens expire after an hour and are revoked when the job ends. Adding a
  product means installing the App on one more repository.

### Option D: One App with full permissions for every role, and the scope check as the only boundary

- **Cost:** the same as C, minus the per-role permission declaration.
- **Consequence:** this is what #322's first draft proposed. It is weaker
  than C for no saving. ADR-0001's own recommendation names the flaw: a
  check is "exactly what a wider credential could edit". A developer token
  with `workflows: write` could rewrite the workflow that runs the check. C
  keeps the token boundary and adds the check on top.

## Recommendation

Recommend C. It is the only option that reduces onboarding to two required
credentials (the App key and one LLM key) while adding a boundary
(`write_scope`) instead of removing one. Its single real cost, the
user-owned board, is a platform limit that every option shares.

## Decision

**Decided:** pending (the human architect decides; see CODEOWNERS)
**Decided by:** pending
**Date:** pending

## Consequences

- **ADR-0001 is amended, not superseded.** Its decision stands: only devops
  can change workflows, and least privilege per role. What changes is the
  mechanism: a permission set declared per role replaces a secret name
  declared per role. `identity.token_secret` stays as the fallback while the
  App is not configured, so this lands without breaking a running system.
  Once `vars.FOUNDRY_APP_CLIENT_ID` is set, the PATs can be deleted.
- **The scope check guards itself by construction.** It runs on
  `pull_request_target`, so both the workflow definition and the script are
  read from the base branch. It never checks out the pull request's code,
  so a PR cannot weaken the copy that judges it. This is ADR-0009's
  principle, applied to the workflow file as well as the script.
- **Commits now need a dispatch to stand behind them.** A commit whose
  `Agent-Role` names a role with no dispatch record on its work item fails
  `scope`. So does a file changed only by a merge commit, because no role
  can be attributed to it. An agent PR may carry a human commit only if it
  is signed and verified to a human account. This is the one piece of
  provenance an agent token cannot forge.
- **Some risk remains:**
  - **Trailers can still be forged among dispatched roles.** If a work item
    was dispatched to both developer and devops, a developer session could
    write a devops trailer. The token boundary still blocks the workflow
    push itself; what remains is devops's other paths (`infra/**`).
  - **A human-authored PR is not scope-checked for human commits.** That is
    deliberate: CODEOWNERS and the human merge cover it.
- **Product layouts differ from the control plane's.** A product's
  `products.yaml` entry may add `write_scope_extra` allow patterns per role,
  for example a root `package.json` for developer. A deny in the pack still
  wins, so this can widen reach to new paths but never re-open a denied
  one. Editing `policies/` is a human-reviewed change.
- **REQ-002's signed per-role identities stay unbuilt.** One App means one
  actor. Role attribution remains the `Agent-Role` trailer, now
  cross-checked against the dispatch record instead of trusted. Ten Apps
  (Option B) remains the path if cryptographic per-role attribution is
  ever required.
- **Follow-up work:** #323 (`foundry-init`) creates the App from the
  manifest, installs it and requires `scope` on each product. #290 routes
  dispatch per product. #324 moves the owner and repo constants into
  config.
