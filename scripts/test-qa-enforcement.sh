#!/usr/bin/env bash
# Tests for the QA veto: scripts/qa-gate.sh and scripts/qa-verdict.sh.
#
# Both scripts talk to GitHub only through `gh`, so a stub `gh` on PATH is
# enough to exercise every branch without touching a real repository.
#
#   bash scripts/test-qa-enforcement.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

export PATH="$WORK/bin:$PATH"
export RUNNER_TEMP="$WORK/tmp"
export GITHUB_REPOSITORY="acme/widgets"
export GITHUB_STEP_SUMMARY="$WORK/summary.md"
mkdir -p "$WORK/bin" "$RUNNER_TEMP"

PASS=0
FAIL=0

# ---------------------------------------------------------------------------
# Stub gh. Behaviour comes from files in $WORK/state, written per test.
# Calls are appended to $WORK/calls.log so tests can assert on side effects.
# ---------------------------------------------------------------------------
cat > "$WORK/bin/gh" <<'STUB'
#!/usr/bin/env bash
state="${STATE_DIR:?}"
echo "gh $*" >> "$state/calls.log"

args=("$@"); jqexpr=""
for ((i=0; i<${#args[@]}; i++)); do
  [ "${args[$i]}" = "--jq" ] && jqexpr="${args[$((i+1))]}"
done
emit() { if [ -n "$jqexpr" ]; then jq -r "$jqexpr"; else cat; fi; }

case "$1 $2" in
  "pr view")   printf '{"body":%s}\n' "$(cat "$state/pr-body.json")" | emit ;;
  "issue view")
      f="$state/issue-$3.json"
      [ -f "$f" ] || { echo "no issue $3" >&2; exit 1; }
      cat "$f" | emit ;;
  "pr comment"|"issue comment"|"issue edit"|"issue reopen") : ;;
  "api "*|"api")
      # events endpoint for the rejection count
      cat "${state}/events.json" | emit ;;
  *) echo "stub gh: unhandled: $*" >&2; exit 1 ;;
esac
STUB
chmod +x "$WORK/bin/gh"

setup() {
  STATE_DIR="$WORK/state"; export STATE_DIR
  rm -rf "$STATE_DIR"; mkdir -p "$STATE_DIR"
  : > "$STATE_DIR/calls.log"
  : > "$GITHUB_STEP_SUMMARY"
  echo '"no body"' > "$STATE_DIR/pr-body.json"
  echo '[]' > "$STATE_DIR/events.json"
}

issue() {  # issue <number> <label...>
  local n=$1; shift
  local labels=""
  for l in "$@"; do labels+="{\"name\":\"$l\"},"; done
  printf '{"number":%s,"labels":[%s]}\n' "$n" "${labels%,}" > "$STATE_DIR/issue-$n.json"
}

pr_body() { jq -Rs . <<<"$1" > "$STATE_DIR/pr-body.json"; }

rejections() {  # rejections <count>
  python3 -c "
import json,sys
n=int(sys.argv[1])
print(json.dumps([{'event':'labeled','label':{'name':'qa:rejected'},
                   'created_at':f'2026-09-0{i+1}T00:00:00Z'} for i in range(n)]
                 + [{'event':'labeled','label':{'name':'type:story'},
                     'created_at':'2026-09-01T00:00:00Z'}]))" "$1" \
    > "$STATE_DIR/events.json"
}

check() {  # check <description> <expected-exit> <actual-exit> [<file-to-grep> <needle>]
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

# assert <description> <"grep"|"!grep"> <needle> <file>
assert() {
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

# assert_count <description> <expected> <pattern> <file>
assert_count() {
  local desc=$1 want=$2 pattern=$3 file=$4 got
  got=$(grep -c -- "$pattern" "$file" || true)
  if [ "$got" = "$want" ]; then
    printf '  ok    %s\n' "$desc"; PASS=$((PASS+1))
  else
    printf '  FAIL  %s\n        expected %s match(es), got %s\n' "$desc" "$want" "$got"
    FAIL=$((FAIL+1))
  fi
}

cd "$REPO_ROOT" || exit 1

# ---------------------------------------------------------------------------
echo "scripts/qa-gate.sh"
# ---------------------------------------------------------------------------

setup; issue 42 "type:story"; pr_body "Closes #42"
PR_NUMBER=42 bash scripts/qa-gate.sh > "$WORK/out" 2>&1
check "passes when the linked item has no verdict" 0 $? "$WORK/out" "QA gate passed"

setup; issue 42 "type:story" "qa:rejected"; pr_body "Closes #42"
PR_NUMBER=42 bash scripts/qa-gate.sh > "$WORK/out" 2>&1
check "fails when the linked item is rejected" 1 $? "$WORK/out" "#42 carries \`qa:rejected\`"

setup; issue 42 "qa:approved"; pr_body "Closes #42"
PR_NUMBER=42 bash scripts/qa-gate.sh > "$WORK/out" 2>&1
check "passes when the linked item is approved" 0 $? "$WORK/out" "QA gate passed"

setup; pr_body "Relates to #42, see also #43"
PR_NUMBER=1 bash scripts/qa-gate.sh > "$WORK/out" 2>&1
check "no closing keyword means nothing to honour" 0 $? "$WORK/out" "closes no work item"

setup; issue 42 "qa:approved"; issue 43 "qa:rejected"; pr_body "Fixes #42 and closes #43"
PR_NUMBER=1 bash scripts/qa-gate.sh > "$WORK/out" 2>&1
check "any rejected item among several blocks" 1 $? "$WORK/out" "#43 carries"

setup; issue 42 "qa:rejected"; pr_body "CLOSES #42"
PR_NUMBER=1 bash scripts/qa-gate.sh > "$WORK/out" 2>&1
check "closing keyword match is case-insensitive" 1 $? "$WORK/out" "#42 carries"

setup; issue 42 "qa:rejected"; pr_body "Resolved #42"
PR_NUMBER=1 bash scripts/qa-gate.sh > "$WORK/out" 2>&1
check "all GitHub closing keywords are honoured" 1 $? "$WORK/out" "#42 carries"

setup; issue 42 "qa:rejected"; pr_body "Closes #42 and Closes #42"
PR_NUMBER=1 bash scripts/qa-gate.sh > "$WORK/out" 2>&1
check "a repeated reference is reported once" 1 $? "$WORK/out" "#42 carries"
assert_count "a repeated reference is deduplicated" 1 '^- #42 carries' "$WORK/out"

# ---------------------------------------------------------------------------
echo
echo "scripts/qa-verdict.sh — close-guard"
# ---------------------------------------------------------------------------

setup; issue 42 "type:story" "qa:rejected"
MODE=close-guard ISSUE=42 bash scripts/qa-verdict.sh > "$WORK/out" 2>&1
check "reopens a closed item under rejection" 0 $? "$WORK/out" "reopened"
assert "called gh issue reopen" grep "gh issue reopen 42" "$STATE_DIR/calls.log"

setup; issue 42 "type:story" "qa:approved"
MODE=close-guard ISSUE=42 bash scripts/qa-verdict.sh > "$WORK/out" 2>&1
check "leaves an approved item closed" 0 $? "$WORK/out" "Nothing to do"
assert "did not reopen an approved item" '!grep' "gh issue reopen" "$STATE_DIR/calls.log"

# ---------------------------------------------------------------------------
echo
echo "scripts/qa-verdict.sh — rejection ladder"
# ---------------------------------------------------------------------------

setup; issue 42 "qa:rejected"; rejections 1
MODE=ladder ISSUE=42 bash scripts/qa-verdict.sh > "$WORK/out" 2>&1
check "one rejection does not escalate" 0 $? "$WORK/out" "no escalation"

setup; issue 42 "qa:rejected"; rejections 2
MODE=ladder ISSUE=42 bash scripts/qa-verdict.sh > "$WORK/out" 2>&1
check "two rejections do not escalate" 0 $? "$WORK/out" "no escalation"

setup; issue 42 "qa:rejected"; rejections 3
MODE=ladder ISSUE=42 bash scripts/qa-verdict.sh > "$WORK/out" 2>&1
check "three rejections escalate" 0 $? "$WORK/out" "needs-human applied"
assert "applied needs-human" grep "gh issue edit 42 --add-label needs-human" "$STATE_DIR/calls.log"
assert "posted the escalation comment" grep "gh issue comment 42" "$STATE_DIR/calls.log"

setup; issue 42 "qa:rejected" "needs-human"; rejections 4
MODE=ladder ISSUE=42 bash scripts/qa-verdict.sh > "$WORK/out" 2>&1
check "does not re-escalate an item already flagged" 0 $? "$WORK/out" "Already escalated"

setup; issue 42 "qa:rejected"; rejections 3
MODE=ladder ISSUE=42 bash scripts/qa-verdict.sh > "$WORK/out" 2>&1
assert "threshold read from role-packs/qa/policy.yaml" grep "threshold 3" "$WORK/out"

setup; issue 42 "qa:rejected"; rejections 3
printf 'verdict:\n  rejection_escalation_threshold: 5\n' > "$WORK/policy.yaml"
QA_POLICY="$WORK/policy.yaml" MODE=ladder ISSUE=42 bash scripts/qa-verdict.sh > "$WORK/out" 2>&1
check "policy file overrides the default threshold" 0 $? "$WORK/out" "threshold 5"

setup
MODE=nonsense ISSUE=42 bash scripts/qa-verdict.sh > "$WORK/out" 2>&1
check "an unknown mode is a hard error" 2 $? "$WORK/out" "unknown MODE"

# ---------------------------------------------------------------------------
echo
echo "scripts/qa-verdict.sh — return-to-ready"
# ---------------------------------------------------------------------------

labels_json() {  # labels_json <name...>
  python3 -c "
import json,sys
print(json.dumps([{'name': n} for n in sys.argv[1:]]))" "$@"
}

setup
LABELS_JSON="$(labels_json status:in-review qa:rejected)" \
  MODE=return-to-ready ISSUE=42 bash scripts/qa-verdict.sh > "$WORK/out" 2>&1
check "an in-review story returns to status:ready" 0 $? "$WORK/out" "returned it to status:ready"
assert "removed status:in-review and added status:ready" grep \
  "gh issue edit 42 --remove-label status:in-review --add-label status:ready" "$STATE_DIR/calls.log"

setup
LABELS_JSON="$(labels_json status:ready qa:rejected)" \
  MODE=return-to-ready ISSUE=42 bash scripts/qa-verdict.sh > "$WORK/out" 2>&1
check "a story already at status:ready is left alone" 0 $? "$WORK/out" "Nothing to do"
assert "made no gh calls" '!grep' "gh " "$STATE_DIR/calls.log"

setup
LABELS_JSON="$(labels_json status:blocked qa:rejected)" \
  MODE=return-to-ready ISSUE=42 bash scripts/qa-verdict.sh > "$WORK/out" 2>&1
check "a story at a different status is left alone" 0 $? "$WORK/out" "Nothing to do"
assert "made no gh calls" '!grep' "gh " "$STATE_DIR/calls.log"

# ---------------------------------------------------------------------------
echo
printf '%s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
