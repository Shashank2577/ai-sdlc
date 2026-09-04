#!/usr/bin/env bash
# Every test_*.py file that unit-tests.yml's discovery loop runs: all of
# them except dashboards/, which dashboards.yml discovers and runs itself
# (a nullglob `for f in dashboards/test_*.py`).
#
# The single definition of that discovery, called by both unit-tests.yml
# (to run the tests) and check-test-wiring.sh (to check whether a given
# test file is one of them) — so the two cannot drift the way the
# enumerated list in unit-tests.yml drifted from reality in #171 (#174).
#
#   bash scripts/list-python-tests.sh [repo-root]
set -euo pipefail

ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

find "$ROOT" \( -path "$ROOT/.git" -o -path "$ROOT/dashboards" -o -name node_modules \) -prune -o \
     -type f -name 'test_*.py' -print |
  sed "s|^$ROOT/||" | sort
