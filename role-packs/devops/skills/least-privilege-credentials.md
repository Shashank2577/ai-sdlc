# Skill — least-privilege credentials

## One token per privilege level, not one token

`GITHUB_TOKEN` is the default and it is deliberately narrow. When a session
is blocked by it, the tempting fix is to hand over the broadest credential
in the repo. Doing that raises every role's reach to unblock one story.

This repo's credentials, and why each exists:

| Secret | Scope | Held by |
|---|---|---|
| `GITHUB_TOKEN` | contents, PRs, issues on this repo | the default for any session whose pack names no secret |
| `FOUNDRY_DEV_TOKEN` | `repo` — deliberately **not** `workflow` | developer, QA, product-manager |
| `FOUNDRY_DEVOPS_TOKEN` | `repo` + `workflow` | devops only |
| `FOUNDRY_TOKEN` | `repo` + `workflow` + `project` | the orchestrator loop and the board sync |

The interesting line is the second. Developer, QA and PM share a credential
because they share a privilege level. None of them can write
`.github/workflows/**`, so none of them can edit the check that reviews
them. That is not a courtesy — it is the only reason the required checks
mean anything.

## Why `workflow` scope is the dangerous one

Branch protection, required checks and the DoD gate are all defined in
files. A credential that can write those files can remove the controls that
constrain it, and no required check can stop that, because the required
check is what it is editing.

So `workflow` scope goes to exactly one role, and that role cannot merge.

## Two symptoms of the same missing scope

Both of these look like unrelated failures and are the same cause:

```
! [remote rejected] refusing to allow a GitHub App to create or update
  workflow `.github/workflows/x.yml` without `workflows` permission
```

and a pull request opened by `github-actions[bot]` whose checks sit at
`action_required`, waiting for someone to press approve. GitHub withholds
`workflow` from `GITHUB_TOKEN` and does not auto-run workflows for
bot-authored PRs. A credential belonging to a person fixes the second; only
`workflow` scope fixes the first.

## Declaring, not hardcoding

A pack declares what it needs:

```yaml
identity:
  token_secret: FOUNDRY_DEVOPS_TOKEN
```

The dispatcher resolves that name. A pack with no `token_secret` does not
compile, for the same reason a pack with no budget does not: a role nobody
can authenticate is not dispatchable.

When the named secret is absent the dispatch still runs on `GITHUB_TOKEN`
and says so loudly. Falling back silently would mean a session failing on a
permission wall with no clue why — which has already cost this repo several
sessions and a lot of inference.
