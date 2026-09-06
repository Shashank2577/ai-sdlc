# Skill — reviewing for security

## Read the diff for attack surface, not for intent

QA reads the acceptance criteria first so it does not inherit the author's
frame. This role has a version of the same trap: reading a PR's own
description of what it does invites you to check that description, not the
code. Read the diff itself first, then decide which of the five categories
below it touches.

## The five things to check, in cost order

1. **Secrets and credentials.** `grep` the diff for anything that looks
   like a token, key, or connection string — committed, logged, echoed into
   a step output, or written into an artifact. Check whether a
   `token_secret` in any touched `pack.yaml` changed tier
   (`FOUNDRY_DEV_TOKEN` → `FOUNDRY_DEVOPS_TOKEN` or `FOUNDRY_TOKEN`) without
   a stated reason.
2. **Permission widening.** Diff every touched `policy.yaml:write_scope`
   and `tools.yaml:shell` against its previous version. A `deny` entry
   removed, or an `allow` entry added that overlaps another role's
   directory, is presumptively wrong until the PR says why.
3. **Injection surface.** Anything built by interpolating attacker-reachable
   text (issue titles, PR bodies, branch names, labels) into a shell
   command, `gh api` call, or workflow `run:` block. Check whether the
   interpolation is quoted, and whether the value could contain a
   backtick, `$(...)`, or a shell metacharacter.
4. **Dependency risk.** A new dependency with no version pin, installed
   before anything reviews it, or with no clear provenance.
5. **Scope this role itself should not touch.** If confirming a finding
   would mean reading a secret's actual value, or writing outside
   `role-packs/security/**`, that is a reason to escalate — not a reason
   to widen your own reach to check.

## Evidence looks like QA's, one level narrower

Every finding cites a file and line, quotes the exact text, and states the
consequence concretely: not "this could be dangerous" but "this lets an
attacker-controlled issue title execute as a shell command in
`scripts/x.sh:42`, because `$ISSUE_TITLE` is interpolated unquoted".

## What this role is not checking

Correctness against acceptance criteria (QA's job), style, or whether the
implementation is elegant. A change can be perfectly correct and still be
this role's rejection — the two verdicts are independent and both can sit
on the same PR.
