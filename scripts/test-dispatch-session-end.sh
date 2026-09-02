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

# run_session_end <issue> <agent_outcome> <cost_usd> <budget_cost_usd> <pr_head_ref|->
# Executes the extracted step and leaves gh's calls in $WORK/calls.log and
# the posted comment body in $WORK/comment.md.
run_session_end() {
  local issue=$1 outcome=$2 cost=$3 budget_cost=$4 pr_ref=$5

  CALLS_LOG="$WORK/calls.log"; : > "$CALLS_LOG"
  COMMENT_OUT="$WORK/comment.md"; : > "$COMMENT_OUT"
  export CALLS_LOG COMMENT_OUT

  if [ "$pr_ref" = "-" ]; then
    echo '[]' > "$WORK/prs.json"
  else
    pr_json "$pr_ref" > "$WORK/prs.json"
  fi
  export PR_LIST_JSON="$WORK/prs.json"

  : > "$WORK/ls-remote.txt"
  export LS_REMOTE_OUT="$WORK/ls-remote.txt"

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
echo "session-end: clean success with a pull request (no label rollback at all)"
# ---------------------------------------------------------------------------
run_session_end 505 success 0.10 5.0 "story/FDY-505-slug"
assert "no issue edit is made" "!grep" 'gh issue edit' "$WORK/calls.log"
assert "no escalation section" "!grep" 'Escalation — human decision required' "$WORK/comment.md"

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
