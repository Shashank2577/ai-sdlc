# Conventions

The authoritative copy is
[`CONVENTIONS.md`](https://github.com/Shashank2577/foundry-program/blob/main/CONVENTIONS.md)
in the repository, and `policies/dod.yaml` is the policy of record for the
Definition of Done. This page is orientation, not a second source of truth — if
the two ever disagree, the repository wins and this page is the bug.

## Branches

`story/FDY-<issue#>-<slug>` for stories, `bug/FDY-<issue#>-<slug>` for defects,
cut from the latest `main`. Nobody pushes to `main`: it is protected, admins
included, force-pushes and deletions off.

## Commit trailers

Four on every commit, enforced by the `dod` required check:

```
Work-Item: Shashank2577/foundry-program#<issue>
Requirement: REQ-0XX
Agent-Role: <orchestrator|pm|architect|developer|qa|devops|techwriter|human>
Harness: <claude-code/x.y|codex/x.y|manual|...>
```

Verify before pushing — this catches the most common DoD failure:

```sh
git log -1 --format='%(trailers:only,unfold)'
```

Pre-automation commits use `Agent-Role: human` and `Harness: manual`. That is
honest provenance, not a gap.

## The label state machine

| Label | Board column | Meaning |
|---|---|---|
| `status:needs-refinement` | Needs Refinement | not ready to dispatch |
| `status:ready` | Ready | maintainer-approved; the dispatcher will run it |
| `status:in-progress` | In Progress | a session is live |
| `status:in-review` | In Review | PR open |
| `status:blocked` | Blocked | escalates after 24h |
| _(closed)_ | Done | closed outranks any stale label |

`role:*` routes assignment. `qa:approved` / `qa:rejected` are verdicts, and
`qa:rejected` blocks closure. `needs-human` means a decision is waiting.

The board is a **view** of these labels, synced by `scripts/sync-project.py`.
Editing a board field by hand is overwritten on the next sync — change the
label instead.

## Definition of Done

Enforced today: four trailers on every commit, a linked work item, and no
unchecked checklist items in the PR body. The rest of `policies/dod.yaml` is
convention until a later story wires it in, and each unenforced item names the
story that will do it.

An unticked box fails the build. That is a forcing function, not a formality:
the only two honest moves are to finish the work or to not open the PR yet. A
gap belongs in the PR's Evidence section, stated — never in a ticked box.
