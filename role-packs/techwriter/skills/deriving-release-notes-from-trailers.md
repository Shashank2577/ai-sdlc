# Skill — deriving release notes from trailers

## The rule

A release note is a fact about a commit that landed, not a summary of a
conversation. If you cannot point at the trailer that proves a change
shipped, it does not go in the notes.

Never write a release note from "what I remember doing this session," from
a PR title alone, or from an issue's description of what was *planned*. A
plan is not a delivery. The trailer on the merged commit is the delivery.

## Where the data lives

Every commit on a PR branch carries four trailers (CONVENTIONS.md):

```
Work-Item: Shashank2577/foundry-program#<issue>
Requirement: REQ-0XX
Agent-Role: <role>
Harness: <harness/version>
```

`dashboards/build.py` already reads this spine for the traceability matrix.
Read that file before writing your own version of the same query — the
pattern is proven, and reimplementing it invites a subtly different (and
wrong) join.

## Pulling the range

For a release covering a range of commits on `main`:

```sh
git log --format='%H%x09%s%x09%(trailers:only,unfold)' <from>..<to>
```

`trailers:only,unfold` strips the commit body down to just the trailer
block, one line per trailer, wrapped values rejoined — the same format
`dashboards/build.py:parse_commits` parses. Group by `Requirement`, list
the `Work-Item` each group closed, and use the commit subject (not your
paraphrase of it) as the starting point for the note's wording.

## What to do when a trailer is missing or malformed

Say so. A commit with no `Requirement` trailer, or a `Work-Item` that does
not resolve to a real issue, is not silently dropped and not silently
guessed at — it is a gap you name in the notes ("N commits in this range
carry no Requirement trailer; see \<shas\>") or an escalation if it blocks
the release notes from being honest at all. Guessing which requirement a
bare commit "probably" belongs to is exactly the fabrication this skill
exists to prevent.

## Shape

Use `templates/release-notes-template.md`: grouped by requirement, one
bullet per commit with its SHA and closed issue, and an explicit
"Untraced" section for anything that would otherwise be silently dropped.

## What good release notes look like

- Grouped by requirement or by work item, not a flat commit list — a reader
  wants "what changed for me," not a git log.
- One line per change, in plain language, sourced from the commit subject
  and the linked issue title — not the diff, and not your inference about
  why it mattered.
- A link back to the PR or the issue for anyone who wants the detail. This
  skill produces the compiled summary; the trailers and the PR are still
  the record.

## Cross-check before publishing

Every entry should be traceable back to a specific commit SHA on `main`. If
you cannot name the SHA, you have not derived the note from the trailers —
you have written it from memory, and it goes back in the queue, not in the
notes.
