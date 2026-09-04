#!/usr/bin/env bash
# Every test_*.py or test-*.sh file must be executed by some workflow, or it
# is dead: nothing runs it, and nothing fails when it starts failing (#69 —
# a shipped test file had 13 of 20 cases failing and every CI check was
# green, because no workflow referenced the file at all).
#
# A test_*.py file is wired if it is one of the files unit-tests.yml's
# discovery loop actually runs — checked by running that exact discovery
# (scripts/list-python-tests.sh), not by grepping workflow YAML for its
# name. Grepping for strings was fine when workflows named each test file,
# but three of them now discover tests by glob or find, so a genuinely
# executed file can match none of those strings. #174: the workaround was a
# comment block in unit-tests.yml listing directory globs for no reason but
# to satisfy this grep — enumeration by another name, and it could go
# stale exactly like the real enumeration did in #171.
#
# Anything list-python-tests.sh doesn't cover (dashboards/, and test-*.sh
# suites, which stay wired individually — out of scope for #174) falls back
# to the crude check: a test file's path, name, or own directory glob (e.g.
# `for f in dashboards/test_*.py; do python3 "$f"; done` in dashboards.yml)
# must appear somewhere under .github/workflows/. That's enough to catch
# the actual failure mode — a test nobody runs — without parsing or
# executing the workflow graph.
#
# A test file that is deliberately not run in CI needs an entry in
# scripts/test-wiring-allowlist.txt (format: "<path><TAB><reason>"); an
# entry with no reason does not count.
#
#   bash scripts/check-test-wiring.sh [repo-root]
set -euo pipefail

ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKFLOWS="$ROOT/.github/workflows"
ALLOWLIST="$ROOT/scripts/test-wiring-allowlist.txt"
PY_DISCOVERED="$(bash "$SCRIPT_DIR/list-python-tests.sh" "$ROOT")"

# allowlist_lookup <path> — sets ALLOW_REASON (possibly empty) and returns 0
# if the path has an entry at all; returns 1 if it has none. A present-but-
# blank reason is a malformed entry, not an exemption — callers must check
# ALLOW_REASON, not just the return code.
allowlist_lookup() {
  local path="$1" p reason
  ALLOW_REASON=""
  [ -f "$ALLOWLIST" ] || return 1
  while IFS=$'\t' read -r p reason; do
    case "$p" in ''|'#'*) continue ;; esac
    if [ "$p" = "$path" ]; then
      ALLOW_REASON="$reason"
      return 0
    fi
  done < "$ALLOWLIST"
  return 1
}

failures=()
malformed=()
allowlisted=()

while IFS= read -r -d '' file; do
  rel="${file#"$ROOT"/}"
  base="$(basename "$rel")"
  dir="$(dirname "$rel")"

  case "$base" in
    test_*.py)
      glob_base="test_*.py"
      if grep -qxF -- "$rel" <<<"$PY_DISCOVERED"; then
        continue
      fi
      ;;
    test-*.sh) glob_base="test-*.sh" ;;
  esac
  if [ "$dir" = "." ]; then
    dir_glob="$glob_base"
  else
    dir_glob="$dir/$glob_base"
  fi

  if grep -rlqF -- "$rel" "$WORKFLOWS" 2>/dev/null \
     || grep -rlqF -- "$base" "$WORKFLOWS" 2>/dev/null \
     || grep -rlqF -- "$dir_glob" "$WORKFLOWS" 2>/dev/null; then
    continue
  fi

  if allowlist_lookup "$rel"; then
    if [ -n "$ALLOW_REASON" ]; then
      allowlisted+=("$rel — $ALLOW_REASON")
    else
      malformed+=("$rel (allowlisted with no reason)")
    fi
    continue
  fi

  failures+=("$rel")
done < <(find "$ROOT" \( -path "*/.git" -o -name node_modules \) -prune -o \
              -type f \( -name 'test_*.py' -o -name 'test-*.sh' \) -print0)

if [ "${#allowlisted[@]}" -gt 0 ]; then
  echo "Allowlisted (not run in CI, by design):"
  printf '  - %s\n' "${allowlisted[@]}"
fi

if [ "${#malformed[@]}" -gt 0 ]; then
  echo "::error::Allowlist entries with no reason:"
  printf '  - %s\n' "${malformed[@]}" >&2
fi

if [ "${#failures[@]}" -gt 0 ]; then
  echo "::error::Test files that no workflow executes:"
  printf '  - %s\n' "${failures[@]}" >&2
fi

if [ "${#failures[@]}" -gt 0 ] || [ "${#malformed[@]}" -gt 0 ]; then
  echo ""
  echo "Wire each one into the workflow that owns the script it tests (see"
  echo "qa-gate.yml, budgets.yml, approval-gate.yml for the pattern, or"
  echo "dashboards.yml for a directory run by glob), or add a reasoned entry"
  echo "to $ALLOWLIST if not running it in CI is correct."
  exit 1
fi

echo "Every test_*.py / test-*.sh file is wired to a workflow (or allowlisted)."
