#!/usr/bin/env bash
# Tests for scripts/standup-escalate.sh against a stub gh.
#
#   bash scripts/test-standup-escalate.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

export PATH="$WORK/bin:$PATH"
export RUNNER_TEMP="$WORK/tmp"
export GITHUB_STEP_SUMMARY="$WORK/summary.md"
mkdir -p "$WORK/bin" "$RUNNER_TEMP"

PASS=0
FAIL=0

cat > "$WORK/bin/gh" <<'STUB'
#!/usr/bin/env bash
echo "gh $*" >> "${CALLS:?}"
STUB
chmod +x "$WORK/bin/gh"

setup() {
  CALLS="$WORK/calls.log"; export CALLS
  : > "$CALLS"; : > "$GITHUB_STEP_SUMMARY"
}

# digest <window> <json-array-of-blocked_stale>
digest() { printf '{"window_hours":%s,"blocked_stale":%s}\n' "$1" "$2" > "$WORK/digest.json"; }

check() {  # check <description> <expected-exit> <actual-exit>
  if [ "$2" = "$3" ]; then printf '  ok    %s\n' "$1"; PASS=$((PASS+1))
  else printf '  FAIL  %s\n        expected exit %s, got %s\n' "$1" "$2" "$3"; FAIL=$((FAIL+1)); fi
}

assert() {  # assert <description> <grep|!grep> <needle> <file>
  local found=0
  grep -qF -- "$3" "$4" && found=1
  if { [ "$2" = "grep" ] && [ "$found" -eq 1 ]; } ||
     { [ "$2" = "!grep" ] && [ "$found" -eq 0 ]; }; then
    printf '  ok    %s\n' "$1"; PASS=$((PASS+1))
  else
    printf '  FAIL  %s\n        %s %q in %s\n' "$1" "$2" "$3" "$4"; FAIL=$((FAIL+1))
  fi
}

cd "$REPO_ROOT" || exit 1

echo "scripts/standup-escalate.sh"

setup; digest 24 '[]'
DIGEST="$WORK/digest.json" bash scripts/standup-escalate.sh > "$WORK/out" 2>&1
check "nothing blocked means no escalation" 0 $?
assert "said so out loud" grep "No escalations" "$WORK/out"
assert "made no gh calls" '!grep' "gh " "$CALLS"

setup; digest 24 '[{"number":9,"title":"stuck","url":"u","hours":30.0,"since":"2026-09-01T06:00:00Z","already_flagged":false}]'
DIGEST="$WORK/digest.json" bash scripts/standup-escalate.sh > "$WORK/out" 2>&1
check "a stale blocked item is escalated" 0 $?
assert "applied needs-human" grep "gh issue edit 9 --add-label needs-human" "$CALLS"
assert "posted the escalation comment" grep "gh issue comment 9" "$CALLS"
assert "reported the duration" grep "blocked 30.0h" "$WORK/out"

setup; digest 24 '[{"number":9,"title":"stuck","url":"u","hours":99.0,"since":"2026-08-29T06:00:00Z","already_flagged":true}]'
DIGEST="$WORK/digest.json" bash scripts/standup-escalate.sh > "$WORK/out" 2>&1
check "an already-flagged item is left alone" 0 $?
assert "no second label" '!grep' "gh issue edit" "$CALLS"
assert "no second comment" '!grep' "gh issue comment" "$CALLS"
assert "explained the skip" grep "already applied" "$WORK/out"

setup; digest 24 '[{"number":9,"title":"a","url":"u","hours":30,"since":"s","already_flagged":false},{"number":10,"title":"b","url":"u","hours":50,"since":"s","already_flagged":true},{"number":11,"title":"c","url":"u","hours":70,"since":"s","already_flagged":false}]'
DIGEST="$WORK/digest.json" bash scripts/standup-escalate.sh > "$WORK/out" 2>&1
check "a mixed batch is handled item by item" 0 $?
assert "flagged the first unflagged item" grep "gh issue edit 9 --add-label needs-human" "$CALLS"
assert "flagged the third" grep "gh issue edit 11 --add-label needs-human" "$CALLS"
assert "skipped the already-flagged one" '!grep' "gh issue edit 10" "$CALLS"
assert "counted correctly" grep "Escalated 2, skipped 1" "$WORK/out"

setup
DIGEST="$WORK/missing.json" bash scripts/standup-escalate.sh > "$WORK/out" 2>&1
check "a missing digest is a hard error" 1 $?
assert "named the missing file" grep "not found" "$WORK/out"

setup; digest 48 '[{"number":9,"title":"a","url":"u","hours":60,"since":"s","already_flagged":false}]'
DIGEST="$WORK/digest.json" bash scripts/standup-escalate.sh > "$WORK/out" 2>&1
assert "threshold comes from the digest, not the script" grep "48h threshold" "$RUNNER_TEMP/blocked-9.md"

echo
printf '%s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
