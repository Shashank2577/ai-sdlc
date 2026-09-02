#!/usr/bin/env bash
# Tests for scripts/gate-sla.sh against a stub gh.
#
#   bash scripts/test-gate-sla.sh
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
# Stub gh. Behaviour comes from files in $STATE_DIR, written per test.
# Calls are appended to calls.log so tests can assert on side effects.
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
  "issue list")   cat "$state/candidates.json" | emit ;;
  "issue view")   cat "$state/comments-$3.json" | emit ;;
  "issue comment") : ;;
  "api "*|"api")
      number=$(grep -oE 'issues/[0-9]+/events' <<<"$*" | grep -oE '[0-9]+')
      f="$state/events-${number}.json"
      [ -f "$f" ] || f="$state/events.json"
      cat "$f" | emit ;;
  *) echo "stub gh: unhandled: $*" >&2; exit 1 ;;
esac
STUB
chmod +x "$WORK/bin/gh"

setup() {
  STATE_DIR="$WORK/state"; export STATE_DIR
  rm -rf "$STATE_DIR"; mkdir -p "$STATE_DIR"
  : > "$STATE_DIR/calls.log"
  : > "$GITHUB_STEP_SUMMARY"
  echo '[]' > "$STATE_DIR/candidates.json"
  echo '[]' > "$STATE_DIR/events.json"
  unset SLA_HOURS GATES_POLICY RUN_URL
}

# candidates <number>...
candidates() {
  python3 -c "
import json, sys
print(json.dumps([{'number': int(n), 'title': 't', 'url': 'u'} for n in sys.argv[1:]]))" "$@" \
    > "$STATE_DIR/candidates.json"
}

# events <number> <hours-ago> [<hours-ago-2> ...] — one needs-human labeled
# event per hours-ago value, timestamped relative to now.
events() {
  local number=$1; shift
  python3 -c "
import json, sys
from datetime import datetime, timedelta, timezone
now = datetime.now(timezone.utc)
out = [{'event': 'labeled', 'label': {'name': 'needs-human'},
        'created_at': (now - timedelta(hours=float(h))).isoformat()}
       for h in sys.argv[1:]]
print(json.dumps(out))" "$@" \
    > "$STATE_DIR/events-${number}.json"
}

# comments <number> [marker-present]
comments() {
  local number=$1
  if [ "${2:-}" = "marker" ]; then
    printf '{"comments":[{"body":"<!-- gate-sla:dispatch_approval -->\\nheld"}]}' \
      > "$STATE_DIR/comments-${number}.json"
  else
    printf '{"comments":[{"body":"unrelated"}]}' > "$STATE_DIR/comments-${number}.json"
  fi
}

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

echo "scripts/gate-sla.sh"

setup
bash scripts/gate-sla.sh > "$WORK/out" 2>&1
check "no held story means no escalation" 0 $?
assert "said so out loud" grep "Nothing to do" "$WORK/out"
assert "posted no comment" '!grep' "gh issue comment" "$STATE_DIR/calls.log"
assert "made only the discovery call" '!grep' "gh issue view" "$STATE_DIR/calls.log"

setup; candidates 9; events 9 30; comments 9
SLA_HOURS=24 bash scripts/gate-sla.sh > "$WORK/out" 2>&1
check "a story held past the SLA gets one comment" 0 $?
assert "posted the SLA comment" grep "gh issue comment 9" "$STATE_DIR/calls.log"
assert "reported the wait" grep "waiting 30.0h" "$WORK/out"

setup; candidates 9; events 9 5; comments 9
SLA_HOURS=24 bash scripts/gate-sla.sh > "$WORK/out" 2>&1
check "a story held less than the SLA is left alone" 0 $?
assert "posted nothing" '!grep' "gh issue comment" "$STATE_DIR/calls.log"
assert "said it was within SLA" grep "within the 24h SLA" "$WORK/out"

setup; candidates 9; events 9 30; comments 9 marker
SLA_HOURS=24 bash scripts/gate-sla.sh > "$WORK/out" 2>&1
check "a story with an existing SLA comment is not re-commented" 0 $?
assert "posted no second comment" '!grep' "gh issue comment" "$STATE_DIR/calls.log"
assert "said so" grep "already posted" "$WORK/out"

setup; candidates 9; events 9 30; comments 9
printf 'gates:\n  dispatch_approval:\n    sla_hours: 48\n' > "$WORK/gates.yaml"
GATES_POLICY="$WORK/gates.yaml" bash scripts/gate-sla.sh > "$WORK/out" 2>&1
check "the policy file's sla_hours is honoured with no code change" 0 $?
assert "used the policy's threshold, not the built-in default" grep "within the 48h SLA" "$WORK/out"
assert "posted nothing at the new threshold" '!grep' "gh issue comment" "$STATE_DIR/calls.log"

setup; candidates 9 11; events 9 30; events 11 3; comments 9; comments 11
SLA_HOURS=24 bash scripts/gate-sla.sh > "$WORK/out" 2>&1
check "a mixed batch is handled item by item" 0 $?
assert "flagged the one past the SLA" grep "gh issue comment 9" "$STATE_DIR/calls.log"
assert "left the one within the SLA alone" '!grep' "gh issue comment 11" "$STATE_DIR/calls.log"

echo
printf '%s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
