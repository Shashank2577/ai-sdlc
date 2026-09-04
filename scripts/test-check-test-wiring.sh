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

# These four use test-*.sh, not test_*.py: shell suites stay grep-only
# (#174 leaves them out of scope), so they exercise the fallback path —
# no-workflow, no-.github, allowlisted, malformed-allowlist — without the
# real discovery below applying and making the fixture's premise false.
# ---------------------------------------------------------------------------
root=$(fixture unwired)
echo "true" > "$root/scripts/test-orphan.sh"
"$CHECK" "$root" > "$WORK/out" 2>&1
check "a test referenced by no workflow fails" 1 $? "$WORK/out" "scripts/test-orphan.sh"

# ---------------------------------------------------------------------------
root=$(fixture no-workflows-dir)
echo "true" > "$root/scripts/test-orphan.sh"
rm -rf "$root/.github"
"$CHECK" "$root" > "$WORK/out" 2>&1
check "a repo with no workflows directory still fails, not crashes" 1 $? "$WORK/out" "scripts/test-orphan.sh"

# ---------------------------------------------------------------------------
root=$(fixture allowlisted)
echo "true" > "$root/scripts/test-orphan.sh"
printf 'scripts/test-orphan.sh\tExercised only by the live cron; tracked in #99.\n' \
  > "$root/scripts/test-wiring-allowlist.txt"
"$CHECK" "$root" > "$WORK/out" 2>&1
check "an allowlisted test with a reason passes" 0 $? "$WORK/out" "Allowlisted"
check "the reason is echoed back" 0 $? "$WORK/out" "tracked in #99"

# ---------------------------------------------------------------------------
root=$(fixture blank-reason)
echo "true" > "$root/scripts/test-orphan.sh"
printf 'scripts/test-orphan.sh\t\n' > "$root/scripts/test-wiring-allowlist.txt"
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

# dashboards/ is excluded from scripts/list-python-tests.sh (dashboards.yml
# discovers and runs those itself), so a file there is the realistic case
# of "excluded from the shared discovery script, but genuinely run by its
# own workflow's glob" — recognised via the grep fallback, not real
# discovery. Also doubles as the pre-existing directory-glob coverage.
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
check "a file excluded from discovery but run by its own workflow's glob counts as wired" \
  0 $? "$WORK/out" "wired"

# ---------------------------------------------------------------------------
root=$(fixture directory-glob-does-not-leak)
mkdir -p "$root/dashboards" "$root/scripts"
echo "def f(): pass" > "$root/dashboards/test_burndown.py"
echo "true" > "$root/scripts/test-orphan.sh"
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
  "$WORK/out" "scripts/test-orphan.sh"

# The point of #174: a python test in a directory no workflow mentions —
# not by name, not by its own directory glob, not even a comment — is
# still reported as wired, because it is picked up by the same discovery
# unit-tests.yml actually runs (scripts/list-python-tests.sh). No workflow
# file is created in this fixture at all.
# ---------------------------------------------------------------------------
root=$(fixture discovered-new-directory)
mkdir -p "$root/newmodule"
echo "def f(): pass" > "$root/newmodule/test_widget.py"
"$CHECK" "$root" > "$WORK/out" 2>&1
check "a new test_*.py in a directory nobody has thought of is wired with no workflow edit" \
  0 $? "$WORK/out" "wired"

# A python test nested inside dashboards/ evades both discovery mechanisms:
# scripts/list-python-tests.sh excludes everything under dashboards/
# wholesale, and dashboards.yml's own `for f in dashboards/test_*.py` is a
# non-recursive nullglob that never reaches a subdirectory. Nothing runs
# it, so the check must still fail (#174 acceptance criterion: a genuinely
# orphaned test file still fails, verified by a fixture, not just asserted).
# ---------------------------------------------------------------------------
root=$(fixture python-genuinely-orphaned)
mkdir -p "$root/dashboards/sub"
echo "def f(): pass" > "$root/dashboards/sub/test_deep.py"
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
check "a python test that evades both discovery loops still fails the check" 1 $? \
  "$WORK/out" "dashboards/sub/test_deep.py"

# ---------------------------------------------------------------------------
echo
printf '%s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
