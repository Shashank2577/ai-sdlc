#!/usr/bin/env bash
# Tests for scripts/diagnose-workflow-push-refusal.sh.
#
# Builds a real temp git repo with a real "origin" remote and reproduces
# the two cases #134 could not tell apart from the push rejection alone:
# a branch that genuinely changes a workflow file (by design — the
# credential boundary is working), and a branch that does not (cause
# unknown). This cannot reproduce GitHub's server-side token-scope check
# itself, only the diff-based reasoning the diagnosis is built on — see
# the header of the script under test.
#
#   bash scripts/test-diagnose-workflow-push-refusal.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$REPO_ROOT/scripts/diagnose-workflow-push-refusal.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PASS=0
FAIL=0

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

# Bare "origin" that a real clone pushes to and diffs against, the same
# shape a dispatched session's checkout is in.
ORIGIN="$WORK/origin.git"
git init --bare --quiet "$ORIGIN"

CLONE="$WORK/clone"
git clone --quiet "$ORIGIN" "$CLONE"
cd "$CLONE" || exit 1
git config user.email test@example.com
git config user.name test
git config commit.gpgsign false

mkdir -p .github/workflows
echo "placeholder" > .github/workflows/existing.yml
echo "hello" > README.md
git add .
git commit --quiet -m "initial main"
git branch -M main
git push --quiet origin main

# ---------------------------------------------------------------------------
echo "by-design: branch genuinely changes a workflow file"
# ---------------------------------------------------------------------------
git checkout --quiet -b bug/FDY-134-adds-workflow main
mkdir -p .github/workflows
echo "name: memory" > .github/workflows/memory.yml
git add .github/workflows/memory.yml
git commit --quiet -m "wire memory tests"

OUT="$WORK/by-design.txt"
bash "$SCRIPT" origin/main > "$OUT" 2>&1
STATUS=$?
if [ "$STATUS" -eq 0 ]; then
  printf '  ok    %s\n' "exits 0"; PASS=$((PASS+1))
else
  printf '  FAIL  exits 0 (got %s)\n' "$STATUS"; FAIL=$((FAIL+1))
fi
assert "names the changed file" grep ".github/workflows/memory.yml" "$OUT"
assert "states this is by design" grep "by design" "$OUT"
assert "tells it not to investigate the token" grep "do not investigate the" "$OUT"
assert "points at the devops handoff" grep "hand the workflow" "$OUT"
assert "does not claim the cause is unknown" "!grep" "cause is not" "$OUT"

# ---------------------------------------------------------------------------
echo "unknown cause: branch touches no workflow file"
# ---------------------------------------------------------------------------
git checkout --quiet -b bug/FDY-134-unrelated main
echo "unrelated change" >> README.md
git add README.md
git commit --quiet -m "unrelated"

OUT="$WORK/unknown.txt"
bash "$SCRIPT" origin/main > "$OUT" 2>&1
STATUS=$?
if [ "$STATUS" -eq 0 ]; then
  printf '  ok    %s\n' "exits 0"; PASS=$((PASS+1))
else
  printf '  FAIL  exits 0 (got %s)\n' "$STATUS"; FAIL=$((FAIL+1))
fi
assert "reports the diff as empty" grep "(empty)" "$OUT"
assert "does not assert a cause" grep "cause is not" "$OUT"
assert "tells it to escalate with the output, not a theory" grep "instead of a theory" "$OUT"
assert "does not claim this is by design" "!grep" "by design" "$OUT"
assert "does not name an unrelated file as the reason" "!grep" "README.md" "$OUT"

# ---------------------------------------------------------------------------
echo "merge base: reported and correct"
# ---------------------------------------------------------------------------
EXPECTED_BASE="$(git merge-base HEAD origin/main)"
assert "prints the actual merge base" grep "$EXPECTED_BASE" "$OUT"

# ---------------------------------------------------------------------------
echo "credential boundary: still unchanged (this issue widens no token)"
# ---------------------------------------------------------------------------
# This cannot exercise GitHub's live server-side scope check — that needs a
# real push with a real token, which no offline test can do. What it can
# prove is the config that *causes* the refusal: only devops declares the
# workflow-scoped secret, and every non-devops role still declares the one
# that lacks it. If either drifts, the refusal this whole diagnosis exists
# to explain would stop happening (or start happening to devops too).
bad_secret=0
for pack in "$REPO_ROOT"/role-packs/*/pack.yaml; do
  role="$(basename "$(dirname "$pack")")"
  [ "$role" = "devops" ] && continue
  secret="$(grep '^  token_secret:' "$pack" | awk '{print $2}')"
  if [ "$secret" = "FOUNDRY_DEVOPS_TOKEN" ]; then
    printf '  FAIL  %s declares the workflow-scoped secret\n' "$role"
    bad_secret=1
  fi
done
if [ "$bad_secret" -eq 0 ]; then
  printf '  ok    %s\n' "no non-devops role declares FOUNDRY_DEVOPS_TOKEN"
  PASS=$((PASS+1))
else
  FAIL=$((FAIL+1))
fi
DEVOPS_SECRET="$(grep '^  token_secret:' "$REPO_ROOT/role-packs/devops/pack.yaml" | awk '{print $2}')"
if [ "$DEVOPS_SECRET" = "FOUNDRY_DEVOPS_TOKEN" ]; then
  printf '  ok    %s\n' "devops still declares the workflow-scoped secret"
  PASS=$((PASS+1))
else
  printf '  FAIL  %s\n' "devops pack.yaml no longer declares FOUNDRY_DEVOPS_TOKEN"
  FAIL=$((FAIL+1))
fi

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
