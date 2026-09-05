#!/usr/bin/env bash
# Tests for the "Session end — report outcome to the work item" step in
# .github/workflows/dispatch.yml.
#
# The step is shell embedded in the workflow, not a standalone script, so
# this extracts its `run:` block with PyYAML and executes it verbatim
# against a stub `gh` and `git` — the same approach used to verify it
# during development, now checked in so a regression fails CI instead of
# waiting for the next live dispatch to find it.
#
#   bash scripts/test-dispatch-session-end.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

STEP_SCRIPT="$WORK/session-end.sh"
python3 - "$REPO_ROOT/.github/workflows/dispatch.yml" "$STEP_SCRIPT" <<'PY'
import sys
import yaml

wf_path, out_path = sys.argv[1], sys.argv[2]
wf = yaml.safe_load(open(wf_path))
for job in wf["jobs"].values():
    for step in job.get("steps", []):
        if step.get("name") == "Session end — report outcome to the work item":
            open(out_path, "w").write(step["run"])
            sys.exit(0)
sys.exit("step not found")
PY

export PATH="$WORK/bin:$PATH"
mkdir -p "$WORK/bin"

PASS=0
FAIL=0

# ---------------------------------------------------------------------------
# Stub gh. Every call is appended to $CALLS_LOG. `gh pr list` and
# `gh issue comment` need actual output/behaviour; everything else (issue
# edit) just needs to be recorded.
# ---------------------------------------------------------------------------
cat > "$WORK/bin/gh" <<'STUB'
#!/usr/bin/env bash
echo "gh $*" >> "${CALLS_LOG:?}"
if [ "$1" = "pr" ] && [ "$2" = "list" ]; then
  cat "${PR_LIST_JSON:?}"
fi
if [ "$1" = "issue" ] && [ "$2" = "view" ]; then
  cat "${ISSUE_LABELS_JSON:?}"
fi
if [ "$1" = "issue" ] && [ "$2" = "comment" ]; then
  for ((i=1; i<=$#; i++)); do
    if [ "${!i}" = "--body-file" ]; then
      j=$((i+1))
      cp "${!j}" "${COMMENT_OUT:?}"
    fi
  done
fi
exit 0
STUB
chmod +x "$WORK/bin/gh"

# git ls-remote is what the step itself calls directly; fetch/rev-parse/
# notes/push are what it and scripts/memory.py (real, not stubbed) call to
# attach an engineering-memory note on an escalation (#120). Each is
# independently controllable via MEMORY_*_FAIL so tests can prove the
# fail-soft rule holds at every one of those points, not just in the
# happy path. `notes` invocations (memory.py's own git calls) are logged
# verbatim to GIT_NOTES_LOG so a test can check the actual --tried/--gotcha
# text that was about to be written, not just whether the call happened.
cat > "$WORK/bin/git" <<'STUB'
#!/usr/bin/env bash
case "$1" in
  ls-remote)
    cat "${LS_REMOTE_OUT:?}"
    exit 0
    ;;
  fetch)
    if [ -n "${GIT_FETCH_LOG:-}" ]; then
      printf '%s\n' "$*" >> "$GIT_FETCH_LOG"
    fi
    if [ "${MEMORY_FETCH_FAIL:-0}" = "1" ]; then
      echo "fake: could not fetch" >&2
      exit 1
    fi
    exit 0
    ;;
  rev-parse)
    if [ "${MEMORY_REVPARSE_FAIL:-0}" = "1" ]; then
      echo "fake: bad revision" >&2
      exit 1
    fi
    echo "${MEMORY_COMMIT:-deadbeefdeadbeefdeadbeefdeadbeefdeadbeef}"
    exit 0
    ;;
  notes)
    if [ -n "${GIT_NOTES_LOG:-}" ]; then
      # One line per argv element — the note body (the `-m` value) has its
      # own embedded newlines, so this lands each "Tried:"/"Gotcha:" line
      # of the formatted note on its own physical line, greppable directly.
      printf '%s\n' "$@" >> "$GIT_NOTES_LOG"
    fi
    if [ "${MEMORY_WRITE_FAIL:-0}" = "1" ]; then
      echo "fake: notes add failed" >&2
      exit 1
    fi
    exit 0
    ;;
  push)
    if [ "${MEMORY_PUSH_FAIL:-0}" = "1" ]; then
      echo "fake: push failed" >&2
      exit 1
    fi
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
STUB
chmod +x "$WORK/bin/git"

assert() {  # assert <description> <"grep"|"!grep"> <needle> <file>
  local desc=$1 mode=$2 needle=$3 file=$4 found=0
  grep -qF -- "$needle" "$file" && found=1
  if { [ "$mode" = "grep" ] && [ "$found" -eq 1 ]; } ||
     { [ "$mode" = "!grep" ] && [ "$found" -eq 0 ]; }; then
    printf '  ok    %s\n' "$desc"; PASS=$((PASS+1))
  else
    printf '  FAIL  %s\n        %s %q in %s\n' "$desc" "$mode" "$needle" "$file"
    FAIL=$((FAIL+1))
  fi
}

pr_json() {  # pr_json <headRefName> — one open PR on that branch
  python3 -c "
import json, sys
print(json.dumps([{'number': 99, 'url': 'https://example/pr/99',
                    'headRefName': sys.argv[1], 'state': 'OPEN'}]))" "$1"
}

labels_json() {  # labels_json <comma-separated names> — issue's current labels
  python3 -c "
import json, sys
names = [n for n in sys.argv[1].split(',') if n]
print(json.dumps({'labels': [{'name': n} for n in names]}))" "$1"
}

ls_remote_line() {  # ls_remote_line <branch> — one `git ls-remote --heads` line
  printf 'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef\trefs/heads/%s' "$1"
}

# run_session_end <issue> <agent_outcome> <cost_usd> <budget_cost_usd> <pr_head_ref|-> \
#   [current_labels] [requires_pr] [no_change_content] [ls_remote_line] \
#   [memory_fetch_fail] [memory_write_fail] [memory_push_fail]
# Executes the extracted step and leaves gh's calls in $WORK/calls.log and
# the posted comment body in $WORK/comment.md. current_labels defaults to
# status:in-progress — the label session-start leaves on a session it did
# not itself dispatch from status:in-review. requires_pr defaults to
# "true" — the pack.yaml:produces default (#99) — so existing callers
# below exercise the same behaviour as a role that declares pull_request.
# no_change_content, when passed (including as an empty string), is
# written verbatim to $RUNNER_TEMP/no-change.md before the step runs, the
# same file a session writes to assert "no change needed" (#129). Omitted
# entirely means no such file — the pre-#129 behaviour.
# ls_remote_line, when passed, is the branch line `git ls-remote` reports —
# needed so $branches is non-empty and the engineering-memory note (#120)
# takes the "fetch the pushed branch" path instead of falling back to HEAD.
# memory_fetch_fail / memory_write_fail / memory_push_fail (default "0")
# each make the corresponding git call the note-writing code makes fail,
# to prove that failure is swallowed rather than taking the step down —
# always reset explicitly here so a failure flag from one test case can
# never leak into the next.
run_session_end() {
  local issue=$1 outcome=$2 cost=$3 budget_cost=$4 pr_ref=$5
  local current_labels=${6:-status:in-progress}
  local requires_pr=${7:-true}
  local no_change_content=${8-__NONE__}
  local ls_remote_line=${9-}
  local mem_fetch_fail=${10:-0} mem_write_fail=${11:-0} mem_push_fail=${12:-0}

  CALLS_LOG="$WORK/calls.log"; : > "$CALLS_LOG"
  COMMENT_OUT="$WORK/comment.md"; : > "$COMMENT_OUT"
  export CALLS_LOG COMMENT_OUT

  if [ "$pr_ref" = "-" ]; then
    echo '[]' > "$WORK/prs.json"
  else
    pr_json "$pr_ref" > "$WORK/prs.json"
  fi
  export PR_LIST_JSON="$WORK/prs.json"

  labels_json "$current_labels" > "$WORK/issue-labels.json"
  export ISSUE_LABELS_JSON="$WORK/issue-labels.json"

  if [ -n "$ls_remote_line" ]; then
    printf '%s\n' "$ls_remote_line" > "$WORK/ls-remote.txt"
  else
    : > "$WORK/ls-remote.txt"
  fi
  export LS_REMOTE_OUT="$WORK/ls-remote.txt"

  : > "$WORK/git-notes.log"
  export GIT_NOTES_LOG="$WORK/git-notes.log"
  : > "$WORK/git-fetch.log"
  export GIT_FETCH_LOG="$WORK/git-fetch.log"
  export MEMORY_COMMIT="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
  export MEMORY_FETCH_FAIL="$mem_fetch_fail"
  export MEMORY_WRITE_FAIL="$mem_write_fail"
  export MEMORY_PUSH_FAIL="$mem_push_fail"
  export MEMORY_REVPARSE_FAIL="0"

  # RUNNER_TEMP is $WORK below, so this is exactly the path the real step
  # reads. Always reset it so no-change.md never leaks between test cases.
  if [ "$no_change_content" = "__NONE__" ]; then
    rm -f "$WORK/no-change.md"
  else
    printf '%s' "$no_change_content" > "$WORK/no-change.md"
  fi

  # A synthetic Claude Code execution log: one `result` record, enough for
  # spend-report.py to compute a real (not "unknown") verdict.
  python3 -c "
import json, sys
print(json.dumps({'type': 'result', 'num_turns': 5, 'total_cost_usd': float(sys.argv[1]),
                   'duration_ms': 60000,
                   'usage': {'input_tokens': 100, 'output_tokens': 100}}))
" "$cost" > "$WORK/execution.json"

  # Two repositories (#208): the work item lives in GITHUB_REPOSITORY (the
  # control plane, unconditionally — Actions sets it to whichever repo the
  # workflow runs in); the pull request lives in PRODUCT_REPO, a different
  # repository on purpose, so any assertion that greps for one and not the
  # other proves the step actually said `--repo` rather than relying on
  # whichever repo happened to be checked out. CP_DIR points at the real
  # repo root so the step's `${CP_DIR}/scripts/...` calls hit the genuine
  # spend-report.py / memory.py, not a stub.
  cd "$REPO_ROOT" && \
  GH_TOKEN=x \
  GITHUB_REPOSITORY=acme/widgets \
  CP_DIR="$REPO_ROOT" \
  PRODUCT_REPO=acme/widgets-product \
  PRODUCT_TOKEN=fake-product-token \
  ISSUE="$issue" ROLE=devops \
  TURNS=30 COST_USD="$budget_cost" TOKENS=400000 WALL_CLOCK=45 \
  MAX_RETRIES=2 BUDGET_SOURCE=policy PRIOR_FAILURES=0 \
  RUN_URL="https://example/run/1" \
  STARTED=success AGENT_OUTCOME="$outcome" \
  EXECUTION_FILE="$WORK/execution.json" \
  REQUIRES_PR="$requires_pr" \
  RUNNER_TEMP="$WORK" GITHUB_STEP_SUMMARY="$WORK/summary.md" \
  bash "$STEP_SCRIPT" > "$WORK/stdout.log" 2>&1
}

cd "$REPO_ROOT" || exit 1

# ---------------------------------------------------------------------------
echo "session-end: generic failure, no pull request (status:ready)"
# ---------------------------------------------------------------------------
run_session_end 501 failure 0.10 5.0 -
assert "removes every status:* label" grep \
  '--remove-label status:ready --remove-label status:in-progress --remove-label status:in-review --remove-label status:blocked --remove-label status:needs-refinement' \
  "$WORK/calls.log"
assert "adds status:ready back" grep '--add-label status:ready --add-label needs-human' "$WORK/calls.log"
assert "does not stay in-review" "!grep" '--add-label status:in-review' "$WORK/calls.log"
assert "escalation offers a redispatch, not a review" grep 'redispatch as-is' "$WORK/comment.md"
assert "state-left-behind names status:ready" grep 'work item returned to' "$WORK/comment.md"

# ---------------------------------------------------------------------------
echo "session-end: failure with an open pull request (stays status:in-review)"
# ---------------------------------------------------------------------------
run_session_end 502 failure 0.10 5.0 "story/FDY-502-slug"
assert "removes every status:* label" grep \
  '--remove-label status:ready --remove-label status:in-progress --remove-label status:in-review --remove-label status:blocked --remove-label status:needs-refinement' \
  "$WORK/calls.log"
assert "adds status:in-review back" grep '--add-label status:in-review --add-label needs-human' "$WORK/calls.log"
assert "does not fall back to status:ready" "!grep" '--add-label status:ready' "$WORK/calls.log"
assert "escalation talks about finishing the PR" grep 'review the open pull request and finish it' "$WORK/comment.md"
assert "escalation does not say redispatch as-is" "!grep" 'redispatch as-is' "$WORK/comment.md"
assert "state-left-behind names status:in-review" grep 'work item stays' "$WORK/comment.md"

# ---------------------------------------------------------------------------
echo "session-end: budget breach with an open pull request (stays status:in-review)"
# ---------------------------------------------------------------------------
run_session_end 503 success 9.99 5.0 "bug/FDY-503-slug"
assert "budget breach detected" grep 'result=failure' "$WORK/comment.md"
assert "adds status:in-review back" grep '--add-label status:in-review --add-label needs-human' "$WORK/calls.log"
assert "does not fall back to status:ready" "!grep" '--add-label status:ready' "$WORK/calls.log"
assert "escalation talks about finishing the PR, not raising the budget blind" grep 'review the open pull request and finish it' "$WORK/comment.md"

# ---------------------------------------------------------------------------
echo "session-end: budget breach with no pull request (status:ready, unchanged behaviour)"
# ---------------------------------------------------------------------------
run_session_end 504 failure 9.99 5.0 -
assert "adds status:ready back" grep '--add-label status:ready --add-label needs-human' "$WORK/calls.log"
assert "escalation still offers the breach ladder" grep 'read the Spend table above before spending again' "$WORK/comment.md"

# ---------------------------------------------------------------------------
echo "session-end: clean success with a pull request, label not moved by the session (#83)"
# ---------------------------------------------------------------------------
run_session_end 505 success 0.10 5.0 "story/FDY-505-slug" "status:in-progress"
assert "removes every status:* label" grep \
  '--remove-label status:ready --remove-label status:in-progress --remove-label status:in-review --remove-label status:blocked --remove-label status:needs-refinement' \
  "$WORK/calls.log"
assert "adds status:in-review, no needs-human" grep '--add-label status:in-review' "$WORK/calls.log"
assert "does not escalate to a human" "!grep" 'needs-human' "$WORK/calls.log"
assert "no escalation section" "!grep" 'Escalation — human decision required' "$WORK/comment.md"

# ---------------------------------------------------------------------------
echo "session-end: clean success with a pull request, already status:in-review (no redundant call)"
# ---------------------------------------------------------------------------
run_session_end 506 success 0.10 5.0 "story/FDY-506-slug" "status:in-review"
assert "no issue edit is made at all" "!grep" 'gh issue edit' "$WORK/calls.log"
assert "no escalation section" "!grep" 'Escalation — human decision required' "$WORK/comment.md"


# ---------------------------------------------------------------------------
echo "session-end: clean success, no pull request, pack requires one (#99 regression)"
# ---------------------------------------------------------------------------
run_session_end 507 success 0.10 5.0 - status:in-progress true
assert "reclassified as no-output" grep 'outcome=no-output' "$WORK/comment.md"
assert "treated as a failure" grep 'result=failure' "$WORK/comment.md"
assert "escalates with needs-human" grep '--add-label status:ready --add-label needs-human' "$WORK/calls.log"
assert "escalation blocker names the missing pull request" grep 'produced no branch and no pull request' "$WORK/comment.md"

# ---------------------------------------------------------------------------
echo "session-end: clean success, no pull request, pack does not require one (PM tracker-only, #99)"
# ---------------------------------------------------------------------------
run_session_end 508 success 0.10 5.0 - status:in-progress false
assert "stays a success" grep 'result=success' "$WORK/comment.md"
assert "not reclassified as no-output" "!grep" 'outcome=no-output' "$WORK/comment.md"
assert "does not escalate" "!grep" 'needs-human' "$WORK/calls.log"
assert "no escalation section" "!grep" 'Escalation — human decision required' "$WORK/comment.md"
assert "no label mutation — the session owns its own labels" "!grep" 'gh issue edit' "$WORK/calls.log"

# ---------------------------------------------------------------------------
echo "session-end: asserted no-change, evidence-bearing reason (#129, would have caught #100)"
# ---------------------------------------------------------------------------
run_session_end 509 success 0.55 5.0 - status:in-progress true "### Findings
Verified the reported defect was already fixed on \`main\`, then swept
every path-filtered workflow in .github/workflows/ for the same class of
bug and found no further instances.

### Evidence
\`grep -rn \"paths:\" .github/workflows/*.yml\` — table of what each
workflow's job reads versus what its \`paths:\` filter declares, all
21 rows consistent."
assert "reclassified as no-change, not no-output" grep 'outcome=no-change' "$WORK/comment.md"
assert "not treated as no-output" "!grep" 'outcome=no-output' "$WORK/comment.md"
assert "stays a success" grep 'result=success' "$WORK/comment.md"
assert "does not escalate" "!grep" 'needs-human' "$WORK/calls.log"
assert "no escalation section" "!grep" 'Escalation — human decision required' "$WORK/comment.md"
assert "durable artefact: the session's reasoning lands in the comment" grep \
  'Verified the reported defect was already fixed on `main`' "$WORK/comment.md"
assert "durable artefact: the evidence lands in the comment too" grep \
  '21 rows consistent' "$WORK/comment.md"
assert "moves to status:blocked for a human to confirm and close" grep \
  '--add-label status:blocked' "$WORK/calls.log"
assert "does not fall back to status:ready — no automatic redispatch" "!grep" \
  '--add-label status:ready' "$WORK/calls.log"

# ---------------------------------------------------------------------------
echo "session-end: no-change.md present but empty — must not count as an assertion (#129)"
# ---------------------------------------------------------------------------
run_session_end 510 success 0.10 5.0 - status:in-progress true ""
assert "still reclassified as no-output" grep 'outcome=no-output' "$WORK/comment.md"
assert "still treated as a failure" grep 'result=failure' "$WORK/comment.md"
assert "still escalates" grep '--add-label status:ready --add-label needs-human' "$WORK/calls.log"
assert "no no-change section — nothing to show" "!grep" 'No change asserted' "$WORK/comment.md"

# ---------------------------------------------------------------------------
echo "session-end: no-change.md present but whitespace-only — must not count either (#129)"
# ---------------------------------------------------------------------------
run_session_end 511 success 0.10 5.0 - status:in-progress true "
   "
assert "still reclassified as no-output" grep 'outcome=no-output' "$WORK/comment.md"
assert "still treated as a failure" grep 'result=failure' "$WORK/comment.md"
assert "still escalates" grep '--add-label status:ready --add-label needs-human' "$WORK/calls.log"

# ---------------------------------------------------------------------------
echo "session-end: no assertion at all, no pull request — the guard is not weakened (#129)"
# ---------------------------------------------------------------------------
run_session_end 512 success 0.10 5.0 -
assert "reclassified as no-output" grep 'outcome=no-output' "$WORK/comment.md"
assert "treated as a failure" grep 'result=failure' "$WORK/comment.md"
assert "escalates with needs-human" grep '--add-label status:ready --add-label needs-human' "$WORK/calls.log"

# ---------------------------------------------------------------------------
echo "session-end: budget breach wins over an asserted no-change (#129)"
# ---------------------------------------------------------------------------
run_session_end 513 success 9.99 5.0 - status:in-progress true "### Findings
Nothing needed to change.

### Evidence
Ran the full test suite; everything passes as-is."
assert "still a failure — spend is a real problem regardless of the conclusion" grep \
  'result=failure' "$WORK/comment.md"
assert "still escalates" grep '--add-label status:ready --add-label needs-human' "$WORK/calls.log"

# ---------------------------------------------------------------------------
echo "session-end: escalation attaches an engineering-memory note to the pushed branch (#120)"
# ---------------------------------------------------------------------------
run_session_end 601 failure 0.10 5.0 - status:in-progress true __NONE__ "$(ls_remote_line story/FDY-601-slug)"
assert "fetches the pushed branch, not just HEAD" grep 'origin story/FDY-601-slug' "$WORK/git-fetch.log"
assert "notes add carries the Attempts text (Tried:)" grep 'Tried: this was attempt 1 on this work item' "$WORK/git-notes.log"
assert "notes add carries the Blocker text (Gotcha:)" grep 'Gotcha: the agent step reported' "$WORK/git-notes.log"
assert "note is attached to the fetched commit and pushed" grep \
  'noted on `deadbeefdeadbeefdeadbeefdeadbeefdeadbeef` and pushed to `refs/notes/foundry`' "$WORK/comment.md"
assert "escalation still fires as before" grep 'Escalation — human decision required' "$WORK/comment.md"

# ---------------------------------------------------------------------------
echo "session-end: escalation with no pushed branch notes HEAD instead (#120)"
# ---------------------------------------------------------------------------
run_session_end 602 failure 0.10 5.0 -
assert "no branch to fetch, HEAD used instead" "!grep" 'origin' "$WORK/git-fetch.log"
assert "still writes a note" grep 'Tried: this was attempt 1' "$WORK/git-notes.log"
assert "note status reports success" grep 'noted on `deadbeefdeadbeefdeadbeefdeadbeefdeadbeef` and pushed' "$WORK/comment.md"

# ---------------------------------------------------------------------------
echo "session-end: notes fetch fails — falls back to HEAD, session still completes (#120 fail-soft)"
# ---------------------------------------------------------------------------
run_session_end 603 failure 0.10 5.0 - status:in-progress true __NONE__ \
  "$(ls_remote_line story/FDY-603-slug)" 1
assert "fetch was attempted and failed" grep 'origin story/FDY-603-slug' "$WORK/git-fetch.log"
assert "still falls back and writes a note on HEAD" grep 'Tried: this was attempt 1' "$WORK/git-notes.log"
assert "note status still reports success via the HEAD fallback" grep \
  'noted on `deadbeefdeadbeefdeadbeefdeadbeefdeadbeef` and pushed' "$WORK/comment.md"
assert "escalation and label rollback still happen" grep '--add-label status:ready --add-label needs-human' "$WORK/calls.log"
assert "the step's own stderr is captured, not left to crash it" "!grep" 'Traceback' "$WORK/stdout.log"

# ---------------------------------------------------------------------------
echo "session-end: memory.py write fails — swallowed, session still completes (#120 fail-soft)"
# ---------------------------------------------------------------------------
run_session_end 604 failure 0.10 5.0 - status:in-progress true __NONE__ "" 0 1
assert "note failure reported in the comment" grep 'could not write a note' "$WORK/comment.md"
assert "does not stop the comment being posted" grep 'gh issue comment' "$WORK/calls.log"
assert "escalation still fires and the label rollback still happens" grep \
  '--add-label status:ready --add-label needs-human' "$WORK/calls.log"

# ---------------------------------------------------------------------------
echo "session-end: notes push fails — note written locally, session still completes (#120 fail-soft)"
# ---------------------------------------------------------------------------
run_session_end 605 failure 0.10 5.0 - status:in-progress true __NONE__ "" 0 0 1
assert "reports the note as unpushed" grep 'the push failed' "$WORK/comment.md"
assert "still names the commit the note lives on" grep 'noted on `deadbeefdeadbeefdeadbeefdeadbeefdeadbeef`' "$WORK/comment.md"
assert "escalation still fires and the label rollback still happens" grep \
  '--add-label status:ready --add-label needs-human' "$WORK/calls.log"

# ---------------------------------------------------------------------------
echo "session-end: no engineering-memory note for a successful session (#120)"
# ---------------------------------------------------------------------------
run_session_end 606 success 0.10 5.0 "story/FDY-606-slug" status:in-progress
assert "no note-writing attempted" "!grep" 'Tried:' "$WORK/git-notes.log"
assert "no engineering-memory line in the comment" "!grep" 'Engineering memory' "$WORK/comment.md"

# ---------------------------------------------------------------------------
echo "session-end: two repositories — PR calls target the product repo, issue calls the control plane (#208)"
# ---------------------------------------------------------------------------
run_session_end 701 success 0.10 5.0 "story/FDY-701-slug" status:in-progress
assert "PR lookup is sent to the product repo" grep \
  "gh pr list --repo acme/widgets-product --state all" "$WORK/calls.log"
assert "PR lookup is not sent to the control plane" "!grep" \
  "gh pr list --repo acme/widgets --state all" "$WORK/calls.log"
assert "issue comment is sent to the control plane" grep \
  "gh issue comment 701 --repo acme/widgets --body-file" "$WORK/calls.log"
assert "issue edit (status:in-review) is sent to the control plane" grep \
  "gh issue edit 701 --repo acme/widgets " "$WORK/calls.log"
assert "no gh call is left without an explicit --repo" "!grep" "gh issue view 701 --json labels" "$WORK/calls.log"

# ---------------------------------------------------------------------------
echo "session-end: two repositories — a failed session escalates against the control-plane issue, still reads the product repo's PRs (#208)"
# ---------------------------------------------------------------------------
run_session_end 702 failure 0.10 5.0 -
assert "PR lookup is still sent to the product repo even with no PR to find" grep \
  "gh pr list --repo acme/widgets-product" "$WORK/calls.log"
assert "label rollback is sent to the control plane" grep \
  "gh issue edit 702 --repo acme/widgets --remove-label status:ready" "$WORK/calls.log"
assert "escalation comment is sent to the control plane" grep \
  "gh issue comment 702 --repo acme/widgets --body-file" "$WORK/calls.log"

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
