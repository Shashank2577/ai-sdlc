#!/usr/bin/env bash
# Tests for scripts/terminal-label.sh.
#
# The script talks to GitHub only through `gh`, so a stub `gh` on PATH is
# enough to exercise every branch without touching a real repository.
#
#   bash scripts/test-terminal-label.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

export PATH="$WORK/bin:$PATH"
mkdir -p "$WORK/bin"

PASS=0
FAIL=0

# ---------------------------------------------------------------------------
# Stub gh. Every call is appended to $CALLS_LOG so tests can assert on it —
# the negative assertions (no calls at all) matter most here, since this
# fires on every issue close.
# ---------------------------------------------------------------------------
cat > "$WORK/bin/gh" <<'STUB'
#!/usr/bin/env bash
echo "gh $*" >> "${CALLS_LOG:?}"
STUB
chmod +x "$WORK/bin/gh"

setup() {
  CALLS_LOG="$WORK/calls.log"; export CALLS_LOG
  : > "$CALLS_LOG"
}

labels_json() {  # labels_json <name...>
  python3 -c "
import json,sys
print(json.dumps([{'name': n} for n in sys.argv[1:]]))" "$@"
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
echo "scripts/terminal-label.sh"
# ---------------------------------------------------------------------------

setup
ISSUE=42 LABELS_JSON="$(labels_json status:in-progress)" bash scripts/terminal-label.sh > "$WORK/out" 2>&1
check "removes a stale status:in-progress label" 0 $? "$WORK/out" "removed status:in-progress"
assert "called gh issue edit --remove-label" grep \
  "gh issue edit 42 --remove-label status:in-progress" "$CALLS_LOG"

setup
ISSUE=42 LABELS_JSON="$(labels_json status:blocked)" bash scripts/terminal-label.sh > "$WORK/out" 2>&1
check "leaves status:blocked in place" 0 $? "$WORK/out" "Nothing to do"
assert "made no gh calls" '!grep' "gh " "$CALLS_LOG"

setup
ISSUE=42 LABELS_JSON="$(labels_json needs-human)" bash scripts/terminal-label.sh > "$WORK/out" 2>&1
check "leaves needs-human in place" 0 $? "$WORK/out" "Nothing to do"
assert "made no gh calls" '!grep' "gh " "$CALLS_LOG"

setup
ISSUE=42 LABELS_JSON="$(labels_json qa:approved)" bash scripts/terminal-label.sh > "$WORK/out" 2>&1
check "leaves a qa:approved verdict in place" 0 $? "$WORK/out" "Nothing to do"
assert "made no gh calls" '!grep' "gh " "$CALLS_LOG"

setup
ISSUE=42 LABELS_JSON="$(labels_json status:in-progress status:blocked needs-human qa:rejected)" \
  bash scripts/terminal-label.sh > "$WORK/out" 2>&1
check "strips only the stale status label from a mixed set" 0 $? "$WORK/out" "removed status:in-progress"
assert "removed status:in-progress" grep \
  "gh issue edit 42 --remove-label status:in-progress" "$CALLS_LOG"
assert_count "made exactly one gh call" 1 '^gh ' "$CALLS_LOG"

setup
ISSUE=42 LABELS_JSON="$(labels_json)" bash scripts/terminal-label.sh > "$WORK/out" 2>&1
check "an issue closed with no labels makes no calls" 0 $? "$WORK/out" "Nothing to do"
assert "made no gh calls" '!grep' "gh " "$CALLS_LOG"

# ---------------------------------------------------------------------------
echo
printf '%s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
