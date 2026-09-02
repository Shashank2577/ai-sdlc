#!/usr/bin/env bash
# Tests for scripts/dod-check.sh's linked_work_item rule (#91 defines the
# policy, #92 enforces it): a closing keyword, or the opt-out phrase, is
# required — a bare `#<issue>` mention is not enough.
#
# BASE_SHA and HEAD_SHA are pinned to the same commit so `git rev-list
# BASE..HEAD` is empty and the commit-trailer check (rule 1) never fires;
# only the PR-body rule (rule 2) is under test here. A stub `gh` returns
# canned PR bodies, same pattern as scripts/test-qa-enforcement.sh.
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
printf '%s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
