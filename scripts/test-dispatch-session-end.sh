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

# git ls-remote is the only git subcommand the step uses.
cat > "$WORK/bin/git" <<'STUB'
#!/usr/bin/env bash
if [ "$1" = "ls-remote" ]; then
  cat "${LS_REMOTE_OUT:?}"
  exit 0
fi
exit 0
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

# run_session_end <issue> <agent_outcome> <cost_usd> <budget_cost_usd> <pr_head_ref|-> [current_labels] [requires_pr] [no_change_content]
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
run_session_end() {
  local issue=$1 outcome=$2 cost=$3 budget_cost=$4 pr_ref=$5
  local current_labels=${6:-status:in-progress}
  local requires_pr=${7:-true}
  local no_change_content=${8-__NONE__}

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

  : > "$WORK/ls-remote.txt"
  export LS_REMOTE_OUT="$WORK/ls-remote.txt"

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

  cd "$REPO_ROOT" && \
  GH_TOKEN=x \
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

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
