# Skill — pull request authoring

The PR is the deliverable. The branch is just how it got there.

## Use the template

`.github/pull_request_template.md`. Every section, in order. `gh pr create`
does not fill it in for you:

```sh
gh pr create --base main --head story/FDY-<n>-<slug> \
  --title "<P0-x>: <the work item title>" \
  --body-file pr-body.md
```

Write the body to a file first. A heredoc in a shell command mangles
backticks and tables, and you will not notice until it is published.

## Closes, not "relates to"

`Closes #<n>` in the body. That is what links the PR to the work item, and
what the DoD check looks for. One work item per PR — if you find yourself
writing `Closes #4, Closes #5`, the branch is doing too much.

## Ticking boxes

Every DoD checkbox has to be ticked for the check to pass. That is a
deliberate forcing function, not a formality: an unticked box fails the
build, so you cannot open a PR you have not actually finished.

Which means the only two honest moves are to **finish the work** or to
**not open the PR yet**. Ticking a box that is not true is the one thing
that breaks the system, because everything downstream — QA, the
traceability matrix, the client-facing status — trusts it.

## Evidence that is actually evidence

The Evidence section is where a reviewer decides whether to believe you.
Paste real output:

```
$ actionlint .github/workflows/dispatch.yml
$ echo $?
0
```

Good evidence:
- Command output, verbatim, with the command shown.
- A table mapping each acceptance criterion to how it was verified.
- A link to a CI run, a published artifact, a screenshot.
- For a change you could not execute: exactly what you *did* verify, and
  what remains unverified.

Not evidence: "tested and working", "should be fine", "logic reviewed",
a restatement of the change with confident adjectives.

## Walk the acceptance criteria

The work item's Gherkin is the contract. Answer it line by line in the
Evidence section — criterion, how it is met, where to look. A reviewer
should not have to hold the issue in one tab and the diff in another to
work out whether you did what was asked.

## State the gaps

If something in the criteria is not met, add a **Gaps** section and say so
plainly: what, why, and what would close it. Include the things you could
not verify, not only the things you did not build.

This costs you nothing. The reviewer finds these anyway, and finding one
you hid is what turns a merge into a rejection.

## After it is open

Move the work item `status:in-progress` → `status:in-review`:

```sh
gh issue edit <n> --remove-label status:in-progress --add-label status:in-review
```

Then stop. Do not merge. Do not approve. Do not push more commits unless
review asks for them.
