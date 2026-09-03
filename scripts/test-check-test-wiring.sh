#!/usr/bin/env bash
# Tests for scripts/check-test-wiring.sh against synthetic fixture repos —
# never this repo's own workflows, so a change here can't be satisfied by
# coincidentally-correct wiring elsewhere.
#
#   bash scripts/test-check-test-wiring.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHECK="$REPO_ROOT/scripts/check-test-wiring.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PASS=0
FAIL=0

check() {  # check <description> <expected-exit> <actual-exit> [<file> <needle>]
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

# fixture <name> — builds a fresh empty repo under $WORK/<name> and prints
# its path.
fixture() {
  local dir="$WORK/$1"
  rm -rf "$dir"
  mkdir -p "$dir/.github/workflows" "$dir/scripts"
  echo "$dir"
}

# ---------------------------------------------------------------------------
root=$(fixture wired)
echo "def f(): pass" > "$root/scripts/test_thing.py"
cat > "$root/.github/workflows/thing.yml" <<'YAML'
on: pull_request
jobs:
  test:
    steps:
      - run: python3 scripts/test_thing.py
YAML
"$CHECK" "$root" > "$WORK/out" 2>&1
check "a test referenced by full path passes" 0 $? "$WORK/out" "wired to a workflow"

# ---------------------------------------------------------------------------
root=$(fixture unwired)
echo "def f(): pass" > "$root/scripts/test_orphan.py"
"$CHECK" "$root" > "$WORK/out" 2>&1
check "a test referenced by no workflow fails" 1 $? "$WORK/out" "scripts/test_orphan.py"

# ---------------------------------------------------------------------------
root=$(fixture no-workflows-dir)
echo "def f(): pass" > "$root/scripts/test_orphan.py"
rm -rf "$root/.github"
"$CHECK" "$root" > "$WORK/out" 2>&1
check "a repo with no workflows directory still fails, not crashes" 1 $? "$WORK/out" "scripts/test_orphan.py"

# ---------------------------------------------------------------------------
root=$(fixture allowlisted)
echo "def f(): pass" > "$root/scripts/test_orphan.py"
printf 'scripts/test_orphan.py\tExercised only by the live cron; tracked in #99.\n' \
  > "$root/scripts/test-wiring-allowlist.txt"
"$CHECK" "$root" > "$WORK/out" 2>&1
check "an allowlisted test with a reason passes" 0 $? "$WORK/out" "Allowlisted"
check "the reason is echoed back" 0 $? "$WORK/out" "tracked in #99"

# ---------------------------------------------------------------------------
root=$(fixture blank-reason)
echo "def f(): pass" > "$root/scripts/test_orphan.py"
printf 'scripts/test_orphan.py\t\n' > "$root/scripts/test-wiring-allowlist.txt"
"$CHECK" "$root" > "$WORK/out" 2>&1
check "an allowlist entry with a blank reason still fails" 1 $? "$WORK/out" "no reason"

# ---------------------------------------------------------------------------
root=$(fixture bash-test)
echo "true" > "$root/scripts/test-thing.sh"
cat > "$root/.github/workflows/thing.yml" <<'YAML'
on: pull_request
jobs:
  test:
    steps:
      - run: bash scripts/test-thing.sh
YAML
"$CHECK" "$root" > "$WORK/out" 2>&1
check "test-*.sh files are found too, not just test_*.py" 0 $? "$WORK/out" "wired"

# ---------------------------------------------------------------------------
root=$(fixture basename-only-reference)
mkdir -p "$root/dashboards"
echo "def f(): pass" > "$root/dashboards/test_status.py"
cat > "$root/.github/workflows/dashboards.yml" <<'YAML'
on: pull_request
jobs:
  build:
    steps:
      - run: cd dashboards && python3 test_status.py
YAML
"$CHECK" "$root" > "$WORK/out" 2>&1
check "a file referenced by basename alone still counts as wired" 0 $? "$WORK/out" "wired"

# ---------------------------------------------------------------------------
root=$(fixture directory-glob-discovery)
mkdir -p "$root/dashboards"
echo "def f(): pass" > "$root/dashboards/test_burndown.py"
cat > "$root/.github/workflows/dashboards.yml" <<'YAML'
on: pull_request
jobs:
  build:
    steps:
      - run: |
          for f in dashboards/test_*.py; do
            python3 "$f"
          done
YAML
"$CHECK" "$root" > "$WORK/out" 2>&1
check "a file covered by a directory-glob discovery loop counts as wired" 0 $? "$WORK/out" "wired"

# ---------------------------------------------------------------------------
root=$(fixture directory-glob-does-not-leak)
mkdir -p "$root/dashboards" "$root/scripts"
echo "def f(): pass" > "$root/dashboards/test_burndown.py"
echo "def f(): pass" > "$root/scripts/test_orphan.py"
cat > "$root/.github/workflows/dashboards.yml" <<'YAML'
on: pull_request
jobs:
  build:
    steps:
      - run: |
          for f in dashboards/test_*.py; do
            python3 "$f"
          done
YAML
"$CHECK" "$root" > "$WORK/out" 2>&1
check "a glob wiring one directory does not wire a test file in another" 1 $? \
  "$WORK/out" "scripts/test_orphan.py"

# ---------------------------------------------------------------------------
echo
printf '%s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
