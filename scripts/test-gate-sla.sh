#!/usr/bin/env bash
# Tests for scripts/gate-sla.sh against a stub gh.
#
#   bash scripts/test-gate-sla.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

export PATH="$WORK/bin:$PATH"
export WORK
export RUNNER_TEMP="$WORK/tmp"
export GITHUB_STEP_SUMMARY="$WORK/summary.md"
export GH_REPO="acme/widgets"
export NOW="2026-09-02T12:00:00Z"
mkdir -p "$WORK/bin" "$RUNNER_TEMP"

PASS=0
FAIL=0

# Stub gh: logs every call, then answers from fixtures the test drops in
# $WORK. `issue list` returns $WORK/issues.json. `api .../<n>/events`
# returns $WORK/events-<n>.json (already the jq-filtered shape the real
# script asks for). `issue view <n>` returns $WORK/comments-<n>.txt
# (already the joined-body shape). `issue comment` is a no-op, just logged.
cat > "$WORK/bin/gh" <<'STUB'
#!/usr/bin/env bash
echo "gh $*" >> "${CALLS:?}"
case "$1" in
  issue)
    case "$2" in
      list) cat "${WORK:?}/issues.json" ;;
      view) cat "${WORK:?}/comments-$3.txt" 2>/dev/null || printf '' ;;
      comment) : ;;
    esac
    ;;
  api)
    num=""
    for a in "$@"; do
      case "$a" in
        repos/*/issues/*/events)
          num="${a#*/issues/}"; num="${num%/events}" ;;
      esac
    done
    cat "${WORK:?}/events-${num}.json" 2>/dev/null || echo '[]'
    ;;
esac
STUB
chmod +x "$WORK/bin/gh"

setup() {
  CALLS="$WORK/calls.log"; export CALLS
  : > "$CALLS"; : > "$GITHUB_STEP_SUMMARY"
  rm -f "$WORK"/events-*.json "$WORK"/comments-*.txt
}

# issues <json-array>
issues() { printf '%s' "$1" > "$WORK/issues.json"; }
events() { printf '%s' "$2" > "$WORK/events-$1.json"; }     # events <number> <json-array>
comments() { printf '%s' "$2" > "$WORK/comments-$1.txt"; }  # comments <number> <text>

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

# --- nothing carries both labels: the no-op case, worth writing first ---
setup; issues '[]'
bash scripts/gate-sla.sh > "$WORK/out" 2>&1
check "no candidates means no-op" 0 $?
assert "said so out loud" grep "Nothing to do" "$WORK/out"
assert "made no comment calls" '!grep' "gh issue comment" "$CALLS"
assert "made no events calls" '!grep' "gh api" "$CALLS"

# --- held past the SLA (24h): exactly one comment, naming the wait ---
setup
issues '[{"number":9,"title":"held","url":"u","labels":[{"name":"needs-human"},{"name":"status:needs-refinement"}]}]'
events 9 '["2026-09-01T06:00:00Z"]'   # 30h before NOW
bash scripts/gate-sla.sh > "$WORK/out" 2>&1
check "an item past SLA is commented on" 0 $?
assert "posted the comment" grep "gh issue comment 9" "$CALLS"
assert "named the wait" grep "30h" "$WORK/tmp/gate-sla-9.md"
assert "cited the SLA" grep "24h" "$WORK/tmp/gate-sla-9.md"

# --- held under the SLA: nothing happens, no comment ---
setup
issues '[{"number":10,"title":"fresh","url":"u","labels":[{"name":"needs-human"},{"name":"status:needs-refinement"}]}]'
events 10 '["2026-09-02T00:00:00Z"]'  # 12h before NOW
bash scripts/gate-sla.sh > "$WORK/out" 2>&1
check "an item under SLA is a no-op" 0 $?
assert "under the SLA, noted" grep "under the 24h SLA" "$WORK/out"
assert "no comment posted" '!grep' "gh issue comment" "$CALLS"

# --- already has the SLA comment: no second comment ---
setup
issues '[{"number":11,"title":"held again","url":"u","labels":[{"name":"needs-human"},{"name":"status:needs-refinement"}]}]'
events 11 '["2026-08-30T06:00:00Z"]'  # well past SLA
comments 11 'earlier chatter
<!-- gate-sla:notice -->
more chatter'
bash scripts/gate-sla.sh > "$WORK/out" 2>&1
check "an already-noted item is left alone" 0 $?
assert "no second comment" '!grep' "gh issue comment" "$CALLS"
assert "explained the skip" grep "already posted" "$WORK/out"

# --- an issue with needs-human but not status:needs-refinement is ignored ---
setup
issues '[{"number":12,"title":"not a gate wait","url":"u","labels":[{"name":"needs-human"}]}]'
bash scripts/gate-sla.sh > "$WORK/out" 2>&1
check "an unrelated needs-human issue is a no-op" 0 $?
assert "made no events calls" '!grep' "gh api" "$CALLS"
assert "made no comment calls" '!grep' "gh issue comment" "$CALLS"

# --- the SLA is read from policies/gates.yaml, not hardcoded ---
setup
issues '[{"number":13,"title":"held","url":"u","labels":[{"name":"needs-human"},{"name":"status:needs-refinement"}]}]'
events 13 '["2026-09-01T00:00:00Z"]'  # 36h before NOW
cat > "$WORK/gates.yaml" <<'YAML'
gates:
  dispatch_approval:
    sla_hours: 48
YAML
GATES_FILE="$WORK/gates.yaml" bash scripts/gate-sla.sh > "$WORK/out" 2>&1
check "a lower-than-actual SLA from a custom policy file is honoured" 0 $?
assert "under the custom 48h SLA, no comment" '!grep' "gh issue comment" "$CALLS"
assert "reported against the custom SLA" grep "under the 48h SLA" "$WORK/out"

echo
printf '%s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
