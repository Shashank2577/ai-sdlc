#!/usr/bin/env bash
# Tests for scripts/dod-check.sh: linked_work_item (#91 defines the policy,
# #92 enforces it — a closing keyword, or the opt-out phrase, is required, a
# bare `#<issue>` mention is not enough), checkbox quoting in fences and
# inline spans (#176), and the checklist_complete deferral form (#173
# defines the policy, #180 enforces it).
#
# BASE_SHA and HEAD_SHA are pinned to the same commit so `git rev-list
# BASE..HEAD` is empty and the commit-trailer check (rule 1) never fires;
# only the PR-body rule (rule 2) is under test in those groups. The
# deferral group needs real Requirement trailers to match against, so it
# gets its own commits in the scratch repo the commit_trailers group
# already sets up. A stub `gh` returns canned PR bodies and issues, same
# pattern as scripts/test-qa-enforcement.sh.
#
#   bash scripts/test-dod-check.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

export PATH="$WORK/bin:$PATH"
export GITHUB_STEP_SUMMARY="$WORK/summary.md"
mkdir -p "$WORK/bin"

SAME_SHA="$(cd "$REPO_ROOT" && git rev-parse HEAD)"
export BASE_SHA="$SAME_SHA" HEAD_SHA="$SAME_SHA" PR_NUMBER=1

PASS=0
FAIL=0

# ---------------------------------------------------------------------------
# Stub gh. Behaviour comes from $STATE_DIR/pr-body.json, written per test.
# ---------------------------------------------------------------------------
cat > "$WORK/bin/gh" <<'STUB'
#!/usr/bin/env bash
state="${STATE_DIR:?}"

args=("$@"); jqexpr=""
for ((i=0; i<${#args[@]}; i++)); do
  [ "${args[$i]}" = "--jq" ] && jqexpr="${args[$((i+1))]}"
done
emit() { if [ -n "$jqexpr" ]; then jq -r "$jqexpr"; else cat; fi; }

case "$1 $2" in
  "pr view")    printf '{"body":%s}\n' "$(cat "$state/pr-body.json")" | emit ;;
  "pr comment") : ;;
  "issue view")
    issue_file="$state/issue-$3.json"
    if [ ! -f "$issue_file" ]; then
      echo "GraphQL: Could not resolve to an Issue with the number of $3." >&2
      exit 1
    fi
    cat "$issue_file" | emit
    ;;
  *) echo "stub gh: unhandled: $*" >&2; exit 1 ;;
esac
STUB
chmod +x "$WORK/bin/gh"

setup() {
  STATE_DIR="$WORK/state"; export STATE_DIR
  rm -rf "$STATE_DIR"; mkdir -p "$STATE_DIR"
  : > "$GITHUB_STEP_SUMMARY"
}

pr_body() { jq -Rs . <<<"$1" > "$STATE_DIR/pr-body.json"; }
# issue <num> <state> <body>  — registers a stub issue for `gh issue view`.
issue() {
  jq -n --arg state "$2" --arg body "$3" '{state: $state, body: $body}' \
    > "$STATE_DIR/issue-$1.json"
}

# check <description> <expected-exit> <actual-exit> [<file-to-grep> <needle>]
check() {
  local desc=$1 want=$2 got=$3
  if [ "$want" != "$got" ]; then
    printf '  FAIL  %s\n        expected exit %s, got %s\n' "$desc" "$want" "$got"
    FAIL=$((FAIL+1)); return
  fi
  if [ $# -ge 5 ] && ! grep -qF -- "$5" "$4"; then
    printf '  FAIL  %s\n        expected %q in %s\n' "$desc" "$5" "$4"
    FAIL=$((FAIL+1)); return
  fi
  printf '  ok    %s\n' "$desc"
  PASS=$((PASS+1))
}

cd "$REPO_ROOT" || exit 1

# ---------------------------------------------------------------------------
echo "scripts/dod-check.sh — linked_work_item"
# ---------------------------------------------------------------------------

setup; pr_body $'Closes #42\n\n- [x] done'
bash scripts/dod-check.sh > "$WORK/out" 2>&1
check "a closing keyword passes" 0 $? "$WORK/out" "DoD check passed"

setup; pr_body $'CLOSES #42\n\n- [x] done'
bash scripts/dod-check.sh > "$WORK/out" 2>&1
check "closing keyword match is case-insensitive" 0 $? "$WORK/out" "DoD check passed"

setup; pr_body $'Fixes #42\n\n- [x] done'
bash scripts/dod-check.sh > "$WORK/out" 2>&1
check "fixes is a valid closing keyword" 0 $? "$WORK/out" "DoD check passed"

setup; pr_body $'Resolves #42\n\n- [x] done'
bash scripts/dod-check.sh > "$WORK/out" 2>&1
check "resolves is a valid closing keyword" 0 $? "$WORK/out" "DoD check passed"

setup; pr_body $'See #42 for context.\n\n- [x] done'
bash scripts/dod-check.sh > "$WORK/out" 2>&1
check "a bare mention with no closing keyword fails" 1 $? "$WORK/out" "no GitHub closing keyword"

setup; pr_body $'Relates to #91 — it does not close it.\n\n- [x] done'
bash scripts/dod-check.sh > "$WORK/out" 2>&1
check "the opt-out phrase passes without a closing keyword" 0 $? "$WORK/out" "DoD check passed"

setup; pr_body $'No issue mentioned here.\n\n- [x] done'
bash scripts/dod-check.sh > "$WORK/out" 2>&1
check "no issue reference at all fails, as before" 1 $? "$WORK/out" "no linked work item"

setup; pr_body $'Closes #42\n\n- [ ] not done'
bash scripts/dod-check.sh > "$WORK/out" 2>&1
check "the checklist rule still fails independently" 1 $? "$WORK/out" "unchecked Definition of Done"

# ---------------------------------------------------------------------------
echo
echo "scripts/dod-check.sh — checkbox quoting in fences and inline spans (#176)"
# ---------------------------------------------------------------------------

setup; pr_body $'Closes #42\n\nDemonstrates the checker:\n\n```\n- [ ] example input\n```\n\n- [x] done'
bash scripts/dod-check.sh > "$WORK/out" 2>&1
check "an unticked box inside a fenced block is ignored" 0 $? "$WORK/out" "DoD check passed"

setup; pr_body $'Closes #42\n\nThe literal text is `- [ ] example` in the input.\n\n- [x] done'
bash scripts/dod-check.sh > "$WORK/out" 2>&1
check "an unticked box inside an inline code span is ignored" 0 $? "$WORK/out" "DoD check passed"

setup; pr_body $'Closes #42\n\n```\n- [ ] quoted example\n```\n\n- [ ] real outstanding item'
bash scripts/dod-check.sh > "$WORK/out" 2>&1
check "a quoted box in a fence does not hide a real unticked box in prose" 1 $? "$WORK/out" "unchecked Definition of Done"

# ---------------------------------------------------------------------------
echo
echo "scripts/dod-check.sh — commit_trailers (#150: split trailer block)"
# ---------------------------------------------------------------------------
# Rule 1 needs real commit history to walk, so these cases get their own
# scratch repo rather than reusing REPO_ROOT's. Each case resets to the base
# commit afterward so the three scenarios do not pile up on one branch.

TRAILER_REPO="$WORK/trailer-repo"
mkdir -p "$TRAILER_REPO"
git -C "$TRAILER_REPO" init -q
git -C "$TRAILER_REPO" config user.email "test@example.com"
git -C "$TRAILER_REPO" config user.name "Test"
git -C "$TRAILER_REPO" commit --allow-empty -q -m base
BASE_TRAILER_SHA="$(git -C "$TRAILER_REPO" rev-parse HEAD)"

cd "$TRAILER_REPO" || exit 1

# Case 1: trailers form one contiguous block and Co-authored-by is appended
# right after with no gap — the shape the harness is supposed to produce.
setup; pr_body $'Closes #42\n\n- [x] done'
git commit --allow-empty -q -F - <<'MSG'
feat: contiguous trailers

Work-Item: Shashank2577/foundry-program#150
Requirement: REQ-005
Agent-Role: devops
Harness: claude-code/2.1.259
Co-authored-by: claude[bot] <41898282+claude[bot]@users.noreply.github.com>
MSG
BASE_SHA="$BASE_TRAILER_SHA" HEAD_SHA="$(git rev-parse HEAD)" PR_NUMBER=1 \
  bash "$REPO_ROOT/scripts/dod-check.sh" > "$WORK/out" 2>&1
check "contiguous trailers with trailing Co-authored-by pass" 0 $? "$WORK/out" "DoD check passed"
git reset -q --hard "$BASE_TRAILER_SHA"

# Case 2: reproduces #150 — a blank line before the appended Co-authored-by
# splits the block. Git's trailer parser then sees only Co-authored-by, and
# the other four trailers — present, readable, correctly formatted — read as
# ordinary body text.
setup; pr_body $'Closes #42\n\n- [x] done'
git commit --allow-empty -q -F - <<'MSG'
feat: split trailer block

Work-Item: Shashank2577/foundry-program#150
Requirement: REQ-005
Agent-Role: devops
Harness: claude-code/2.1.259

Co-authored-by: claude[bot] <41898282+claude[bot]@users.noreply.github.com>
MSG
BASE_SHA="$BASE_TRAILER_SHA" HEAD_SHA="$(git rev-parse HEAD)" PR_NUMBER=1 \
  bash "$REPO_ROOT/scripts/dod-check.sh" > "$WORK/out" 2>&1
got=$?
check "split trailer block still fails the check" 1 "$got"
check "split trailer block names the real cause, not \"missing\"" "$got" "$got" \
  "$WORK/out" "outside the trailer block git recognizes"
check "split trailer block states the contiguity rule" "$got" "$got" \
  "$WORK/out" "one contiguous block at the end"
git reset -q --hard "$BASE_TRAILER_SHA"

# Case 3: a trailer that is genuinely absent — nowhere in the message, not
# even outside the block — must still report as missing, distinguishably
# from case 2.
setup; pr_body $'Closes #42\n\n- [x] done'
git commit --allow-empty -q -F - <<'MSG'
feat: missing trailer

Work-Item: Shashank2577/foundry-program#150
Requirement: REQ-005
Agent-Role: devops
MSG
BASE_SHA="$BASE_TRAILER_SHA" HEAD_SHA="$(git rev-parse HEAD)" PR_NUMBER=1 \
  bash "$REPO_ROOT/scripts/dod-check.sh" > "$WORK/out" 2>&1
got=$?
check "a genuinely missing trailer still fails" 1 "$got" "$WORK/out" "is missing trailer \`Harness:\`"
if grep -qF "outside the trailer block" "$WORK/out"; then
  printf '  FAIL  %s\n        did not expect "outside the trailer block" in output\n' \
    "a genuinely missing trailer is not called \"outside the block\""
  FAIL=$((FAIL+1))
else
  printf '  ok    %s\n' "a genuinely missing trailer is not called \"outside the block\""
  PASS=$((PASS+1))
fi
git reset -q --hard "$BASE_TRAILER_SHA"

# ---------------------------------------------------------------------------
echo
echo "scripts/dod-check.sh — checklist_complete deferral (#173 policy, #180 check)"
# ---------------------------------------------------------------------------
# The deferral check matches the referenced issue's body against this PR's
# own Requirement ids, which only exist on a real commit trailer — so this
# group needs one commit, not the empty-rev-list SAME_SHA trick above.
# REQ-010 mirrors #161, the live case #180 verifies against: its one
# unmet criterion was "`environment:` used so the platform enforces the
# gate — verified by a real dispatch to `prod` pausing, with the run
# linked in Evidence", which no session could self-satisfy before merge.

git commit --allow-empty -q -F - <<'MSG'
feat: deploy workflow prod gate

Work-Item: Shashank2577/foundry-program#161
Requirement: REQ-010
Agent-Role: devops
Harness: claude-code/2.1.259
MSG
DEFER_HEAD="$(git rev-parse HEAD)"

run_defer() {
  BASE_SHA="$BASE_TRAILER_SHA" HEAD_SHA="$DEFER_HEAD" PR_NUMBER=1 \
    bash "$REPO_ROOT/scripts/dod-check.sh" > "$WORK/out" 2>&1
}

setup
issue 172 OPEN "Tracks the human approval for REQ-010's production gate."
pr_body $'Closes #161\n\n- [~] `environment:` used so the platform enforces the gate — verified by a real dispatch to `prod` pausing, with the run linked in Evidence — deferred to #172: needs a human reviewer to approve the pending deployment; no session can self-approve it'
run_defer
check "#161's live case: a valid deferral (open issue, matching REQ, stated reason) passes" 0 $? "$WORK/out" "DoD check passed"

setup
issue 172 OPEN "Tracks the human approval for REQ-010's production gate."
pr_body $'Closes #161\n\n- [~] verified by a real dispatch to prod pausing — deferred: needs a human reviewer'
run_defer
check "a deferral with no issue number fails" 1 $? "$WORK/out" "does not match the required form"

setup
issue 172 CLOSED "Tracks the human approval for REQ-010's production gate."
pr_body $'Closes #161\n\n- [~] verified by a real dispatch to prod pausing — deferred to #172: needs a human reviewer'
run_defer
check "a deferral naming a closed issue fails" 1 $? "$WORK/out" "which is not open"

setup
pr_body $'Closes #161\n\n- [~] verified by a real dispatch to prod pausing — deferred to #9999: needs a human reviewer'
run_defer
check "a deferral naming a nonexistent issue fails" 1 $? "$WORK/out" "which does not exist"

setup
issue 172 OPEN "Tracks the human approval for REQ-010's production gate."
pr_body $'Closes #161\n\n- [~] verified by a real dispatch to prod pausing — deferred to #172:'
run_defer
check "a deferral with no stated reason fails" 1 $? "$WORK/out" "states no reason"

setup
issue 172 OPEN "No matching requirement mentioned here."
pr_body $'Closes #161\n\n- [~] verified by a real dispatch to prod pausing — deferred to #172: needs a human reviewer'
run_defer
check "a deferral to an issue with no matching Requirement id fails" 1 $? "$WORK/out" "names none of this PR's Requirement ids"

setup
pr_body $'Closes #161\n\n- [ ] verified by a real dispatch to prod pausing'
run_defer
check "a plain unticked box is still not a deferral and fails" 1 $? "$WORK/out" "unchecked Definition of Done"

setup
pr_body $'Closes #161\n\n- [x] verified by a real dispatch to prod pausing'
run_defer
check "all boxes ticked, no deferral needed, passes" 0 $? "$WORK/out" "DoD check passed"

git reset -q --hard "$BASE_TRAILER_SHA"

cd "$REPO_ROOT" || exit 1

# ---------------------------------------------------------------------------
echo
printf '%s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
