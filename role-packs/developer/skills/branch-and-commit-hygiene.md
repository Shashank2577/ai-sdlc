# Skill — branch and commit hygiene

## Cut the branch first

Before the first edit, not after:

```sh
git fetch origin
git checkout -b story/FDY-<issue#>-<slug> origin/main
```

`<slug>` is two or three words from the work item title, lowercase, hyphens.
`story/FDY-3-dispatcher`, not `story/FDY-3-implement-the-dispatcher-workflow-v0`.

Cutting from `origin/main` rather than whatever is checked out is the point.
A branch cut from a stale local `main` produces a diff full of other people's
changes and a reviewer who cannot see yours.

## Trailers on every commit

```sh
git commit -F - <<'MSG'
feat(dispatch): one line, imperative, no trailing period

Why this change exists and what a reviewer should look at. Wrap at 72.
The subject says what; the body says why. If the why is obvious, the body
can be short — but "update files" is never a subject line.

Work-Item: Shashank2577/foundry-program#3
Requirement: REQ-002, REQ-003
Agent-Role: developer
Harness: claude-code/2.1.220
MSG
```

Git only recognizes the final **contiguous block** of the message as
trailers. The four trailers must sit together at the very end, with no
blank line inside the block — including after any `Co-authored-by:` line
a harness appends below them. A blank line anywhere in that block splits
it: git only reads the piece below the split as trailers, and everything
above it silently becomes body text that no trailer-reading tool (or the
DoD check) will see. This is why the example above puts the trailers last
and leaves no blank line before where `Co-authored-by:` would land.

Verify before you push — this is one command and it catches the mistake
that fails the DoD check most often:

```sh
git log -1 --format='%(trailers:only,unfold)'
```

Four lines out, or the commit is wrong. If fewer come out than you wrote,
suspect a blank line inside the trailer block before assuming a trailer is
missing.

For a whole branch:

```sh
git log origin/main..HEAD --format='%h %s%n%(trailers:only,unfold)'
```

## Getting the trailer values right

- **Work-Item** is `<owner>/<repo>#<issue>`, fully qualified. Not `#3`.
- **Requirement** comes from the work item, not from your judgement. The
  issue says `→ REQ-002, REQ-003`; use exactly those.
- **Agent-Role** is the role you were dispatched as. If a human is typing,
  it is `human`.
- **Harness** is `claude-code/<version>` from `claude --version`, or
  `manual` when a human did it by hand. Making up a version is worse than
  omitting the commit.

## Amending

If you have not pushed, amending is fine. Once pushed, add a follow-up
commit instead. Force-pushing a shared branch to fix a trailer destroys the
audit trail the trailer exists to create.

## What not to commit

- Scratch files, `.log`, `.tmp`, editor state, anything under a temp dir.
- Generated output that CI regenerates.
- Anything you cannot explain in the PR body.

Run `git status --short` before `git add`. Then `git add <paths>` — never
`git add -A` on a tree you have not just inspected.
