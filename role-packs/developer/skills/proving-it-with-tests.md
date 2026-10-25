---
description: 'Before opening a PR, run the tests that exercise the change, show the exact commands and output in the Evidence section, and make sure each new test fails without the change. Use when finishing any code change.'
---
# Skill — proving it with tests

QA re-runs your commands. A PR whose Evidence says "tests pass" when none
ran, or whose new test doesn't exercise the change, bounces and costs a
second session.

**Use CI's commands, not guesses.** What gates a merge is whatever
`.github/workflows/*.yml` runs in your work tree. In the control plane that's
`bash scripts/test-*.sh` plus the files from `bash scripts/list-python-tests.sh`.
Quote the exact commands in Evidence.

**Red, then green.**
1. Write the test for what the work item asks, and watch it fail for the
   reason you expect. A test that passes first time probably isn't testing
   your change.
2. Make it pass with the smallest change that does.
3. Tidy only what you wrote, then re-run.

**A fix proves it guards.** Run the new test against `main`'s version too:
`git show origin/main:<path> > <path>`, run the test, then
`git checkout -- <path>`. Show it failing there and passing with your change.

**Test behaviour, not internals.** Assert outputs, labels written and exit
codes, not which calls were made. Reuse the neighbouring tests' fixtures;
several suites run a workflow's real `run:` step against a stub `gh`. Name
each test for the behaviour it pins. Never skip, delete or weaken a test to
get green.

**Before the PR:**
- Every changed behaviour has a test.
- The full suite passes.
- A new test file is wired into a workflow (`scripts/check-test-wiring.sh`).

Don't re-run a command that already passed unless the code has changed;
turns are budget.

_Adapted from `test-driven-development`,
[addyosmani/agent-skills](https://github.com/addyosmani/agent-skills),
MIT License, Copyright (c) 2025 Addy Osmani._
