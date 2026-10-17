# Behavioural evals

Do a role's skills change what a dispatched session actually does? A
skill that compiles, installs and shows up in the prompt can still be
ignored. These evals check that by running a real session and grading
what it did (#320).

They are modelled on Tier 3 of
[addyosmani/agent-skills' evals](https://github.com/addyosmani/agent-skills/tree/main/evals):
headless `claude -p` in a throwaway git repo built from a fixture, with
the transcript graded against `expectations[]` by a second `claude -p`.
Every run spends tokens, so they run **on demand only, never in CI**.
Tiers 1 and 2 are covered elsewhere: `compiler/test_compile_pack.py`
checks skill structure, and `scripts/test-dispatch-skills.sh` checks
that skills and policy reach the session.

## Running

```sh
python3 evals/run-behavioral.py --dry-run     # build every eval, run nothing
python3 evals/run-behavioral.py               # every case
python3 evals/run-behavioral.py qa --model claude-opus-5-5 --keep
```

Results land in `evals/results/<timestamp>/<role>-<id>/`, which is
gitignored. Each run directory holds `prompt.md`, `trace.jsonl`,
`transcript.md`, `gh-calls.jsonl`, `git-state.txt` and `grading.json`
(skill-creator's shape, plus a `run` block with the Claude Code version,
model, turns, cost and which skills the session invoked). The exit code is
non-zero when any expectation fails.

Skill invocation is stochastic. Read one run as a data point, not a
verdict. When you report numbers, pin `--model` and give the Claude Code
version.

**The session runs with `--permission-mode bypassPermissions`**, as it
does under dispatch. It can run any command on your machine, inside a
temp directory. Run the evals where you are happy for that to happen.

## What the session gets

As close to a real dispatch as a laptop allows, built from the real
parts rather than copies of them:

- The role pack is compiled by `compiler/compile-pack.py`.
- The skills are installed by dispatch.yml's own *Install the role's
  skills* step, into a throwaway `HOME`. They are then moved into the
  repo's `.claude/skills/` and excluded from git. Under dispatch they stay
  in `~/.claude/skills/` (user scope). Here they use project scope, so the
  eval never writes to your own `~/.claude`. The files and the loader are
  the same either way.
- The prompt is built by dispatch.yml's own *Assemble the session prompt*
  step, from the eval's `issue`, with the real charter and CONVENTIONS.md.
- `gh` is `evals/gh_stub.py`. The work item and the pull request exist
  only in the eval's state directory. Every call is logged, so the grader
  sees what the session did to the tracker, not what it says it did.
  `GH_TOKEN` is set to a dead value, so real `gh` could not authenticate
  even if the session found it.
- `--setting-sources project,local` and `--strict-mcp-config` keep your
  own settings, plugins, hooks, skills and MCP servers out of the session.
  The compiled `settings.json` is passed with `--settings`, as dispatch
  passes it.

## Case format

One file per role: `evals/cases/<role>.json`.

```json
{
  "role": "qa",
  "evals": [{
    "id": "exactly-one-verdict",
    "kind": "execution",
    "files": ["pricing"],
    "issue": {"number": 7, "title": "...", "body": "..."},
    "pr": {"number": 12, "title": "...", "headRefName": "bug/FDY-7-...",
           "overlay": "qa-bulk-discount-pr", "body": "..."},
    "expected_output": "...",
    "expectations": ["..."]
  }]
}
```

- `files[]` are directories under `evals/fixtures/`, copied into the repo
  and committed on `main` as the baseline.
- `issue` is the work item. There is no `prompt` field: the prompt is
  whatever dispatch.yml builds from the issue, which is the thing under
  test.
- `pr` is optional. Its `overlay` fixture is committed on `headRefName`,
  and the stub serves it as the open pull request. A review role (`qa`,
  `security`, `operations`) is dispatched from `status:in-review` and
  reviews it.
- `expectations[]` are behaviours a grader can check against the
  transcript, the gh call log and the final git state. Do not write
  phrasings.

Fixture test files are named `*_test.py`, not `test_*.py`. This repo's
own test discovery (`scripts/list-python-tests.sh`) would otherwise run
them as its own tests.

## Cases

| Case | Checks | Skills it leans on |
|---|---|---|
| `developer/tests-before-pr` | The repo's own test command runs green after the last code change and before `gh pr create`. The fix carries a boundary test, and the PR follows the template. | `pull-request-authoring`, `branch-and-commit-hygiene` |
| `qa/exactly-one-verdict` | Exactly one verdict label, posted after the comment. The PR's tests pass but it breaks a criterion, so the right verdict is `qa:rejected`. Nothing is edited, committed or merged. | `issuing-a-verdict`, `reading-acceptance-criteria` |
