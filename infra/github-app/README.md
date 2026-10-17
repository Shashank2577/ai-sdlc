# The Foundry GitHub App: design

This is the design behind ADR-0011 (#322). One GitHub App replaces
`FOUNDRY_TOKEN`, `FOUNDRY_DEV_TOKEN` and `FOUNDRY_DEVOPS_TOKEN`. Each
dispatch mints a short-lived installation token, scoped to the role it
runs. A required check, `scope`, enforces each role's `write_scope` on the
PR diff, which no token can express.

## What an adopter configures

| Kind | Name | Where | Required |
|---|---|---|---|
| Variable | `FOUNDRY_APP_CLIENT_ID` | control plane | yes |
| Secret | `FOUNDRY_APP_PRIVATE_KEY` | control plane | yes |
| Secret | `ANTHROPIC_API_KEY` (or `CLAUDE_CODE_OAUTH_TOKEN`) | control plane | yes |
| Secret | `FOUNDRY_PROJECT_TOKEN` (classic PAT, `project` scope only) | control plane | only for a board owned by a *user* account |
| Variable | `FOUNDRY_CONTROL_PLANE` (`owner/repo`) | each product | yes, set by foundry-init |

That is two credentials, the App key and the LLM key, plus one optional
PAT. The PAT exists because GitHub exposes no App permission for user-owned
Projects v2. Organization projects are covered by the App's
`organization_projects` permission.

`scripts/foundry-init.py --create-app` performs the App creation (#323):
1. It posts `manifest.json` to GitHub's [manifest flow], so the owner
   clicks once.
2. It catches the redirect on `127.0.0.1`.
3. It exchanges the code for the private key.
4. It stores the client ID and the key with `gh variable set` and
   `gh secret set`.
5. It opens the installation page.

The key never touches disk or the terminal. The name in `manifest.json`
is a placeholder: App names are global, so init sends `foundry-<owner>`.

[manifest flow]: https://docs.github.com/en/apps/sharing-github-apps/registering-a-github-app-from-a-manifest

## Three boundaries

```
                 ┌──────────── dispatch.yml (control plane) ─────────────┐
 pack.yaml ───►  │ compile-pack ─► github-permissions ─► create-github-  │
 identity.       │                                       app-token@v3    │
 github_         │                                       (only those)    │
 permissions     │   session-start comment, as github-actions[bot]:      │
                 │   <!-- foundry:dispatch-start role= product= run= --> │
                 └───────────────┬───────────────────────────────────────┘
                                 │ token (1 h, revoked at job end)
                                 ▼
                    agent pushes branch, opens PR as <app>[bot]
                                 │
           ┌─────────────────────┴───────────────────────┐
           ▼                                              ▼
  GitHub refuses a push to                 scope (pull_request_target, base copy)
  .github/workflows/** unless              commit Agent-Role ∈ verified dispatch
  the token has workflows:write            roles; each file ∈ that role's
  (only devops's pack declares it)         write_scope; workflows ⇒ devops
```

1. **Token: what GitHub lets the session do at all.**
   `pack.yaml:identity.github_permissions` is a closed set (`contents`,
   `pull-requests`, `issues`, `workflows`, `actions`, `checks`,
   `statuses`; `read` or `write`), and the compiler refuses anything else.
   - Only `devops` declares `workflows: write`.
     `compiler/test_compile_pack.py` fails if another pack does.
   - `security` and `operations` get `contents: read`, because they commit
     nothing.
   - `orchestrator` gets `actions: write` to start dispatches, and no
     content write.
   - A pack with no declaration is refused at mint time. Minting with no
     `permission-*` inputs would inherit the installation's full set.
2. **Path: what the role may change.** `scripts/check-write-scope.py`,
   run by `.github/workflows/scope-check.yml`:
   - For each non-merge commit, read its `Agent-Role`.
   - That role must have a **verified dispatch record** on the work item,
     which is taken from the branch name:
     - the record is a comment by `github-actions[bot]` in the control
       plane;
     - the comment must *start* with the marker, so text quoted into a
       comment does not count;
     - its run must be a `workflow_dispatch` run of `dispatch.yml` whose
       job is named `#<item> as <role> on <product>`.
   - Every file in the net diff (both sides of a rename) must be changed
     by at least one non-merge commit. Every agent commit touching it must
     be inside that role's `write_scope` (deny first, then allow), widened
     only by the product's `write_scope_extra` allow patterns.
   - `.github/workflows/**` additionally requires `devops`.
   - Human commits pass. On a bot-authored PR they count only when GitHub
     verified the signature to a person's account.
3. **Actor: who GitHub says did it.** Agent actions are `<app>[bot]`, so
   ADR-0007's `is_human()` again means a person. claude-code-action's
   human-actor check is satisfied by naming exactly this App in
   `allowed_bots`, not `*`.

### Why `pull_request_target`

`pull_request` takes the workflow file from the PR's merge ref. A devops PR
could then rewrite the job that checks it. `pull_request_target` takes it
from the base branch, and the job checks out the control plane's default
branch for the script. The PR's code is never checked out. That makes the
check safe for fork PRs as well.

## Token reach per workflow

| Workflow | Token | Permissions | Reach |
|---|---|---|---|
| `dispatch.yml` | minted per role | the role pack's `github_permissions` | the product repo, plus the control plane if the same owner holds both |
| `orchestrate.yml`, `refinement.yml` | minted | `actions:write issues:write contents:read pull-requests:read` | owner-wide, since product PRs live in product repos |
| `project-sync.yml` | `FOUNDRY_PROJECT_TOKEN` | classic PAT, `project` | the board |
| `scope-check.yml`, gates, verdicts | `GITHUB_TOKEN` | per workflow | this repo, reading the public control plane |

Every App-token site falls back to the old PAT secret when
`FOUNDRY_APP_CLIENT_ID` is unset, so the change lands without breaking a
running system.

## Migrating the live control plane

1. Run `foundry-init.py --create-app`, or create the App from
   `manifest.json` by hand. Install it on `ai-sdlc` and every product.
2. Set `FOUNDRY_APP_CLIENT_ID` and `FOUNDRY_APP_PRIVATE_KEY`. From the next
   dispatch on, sessions run as `<app>[bot]`. Their PRs and comments stop
   looking like the owner's.
3. Watch one dispatch per role. Then add `scope` to `main`'s required
   checks:
   ```
   gh api -X POST repos/Shashank2577/ai-sdlc/branches/main/protection/required_status_checks/contexts -f 'contexts[]=scope'
   ```
4. Delete `FOUNDRY_TOKEN`, `FOUNDRY_DEV_TOKEN` and `FOUNDRY_DEVOPS_TOKEN`,
   and revoke the PATs on the account. If the board is user-owned, create
   `FOUNDRY_PROJECT_TOKEN` with `project` scope only.
5. Keep the App off branch protection's bypass list. It is an actor like
   any other.

## What the check found on its first run

Before landing, the check ran read-only against recent merged and open
PRs. #319 and #295 passed. The other two failed:
- **#302** carries a commit claiming `devops` that changed
  `compiler/compile-pack.py`, which devops's pack denies.
- **#301** carries a `devops` commit changing `dashboards/build.py`.

Neither was caught at the time, because nothing read `write_scope`.

## Known limits

- **One App means one actor.** Per-role signed identities (REQ-002) are
  still unbuilt; the trailer, now cross-checked, remains the attribution.
- **Trailers can be forged among dispatched roles.** If both developer and
  devops were dispatched on one item, a developer session could forge a
  devops trailer. Workflow pushes are still blocked by the token.
  `infra/**` is not.
- **Cross-owner products.** A product under a different owner than the
  control plane gets a token that cannot comment on the control-plane work
  item. Same-owner setups are the supported case.
- **A private control plane.** `scope-check.yml` in a product reads the
  control plane with `GITHUB_TOKEN`. That works for a public control
  plane. A private one needs the App token there too, which is follow-up
  work.
