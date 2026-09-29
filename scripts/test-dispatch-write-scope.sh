#!/usr/bin/env bash
# The session prompt must state the role's write scope (#233). The compiled
# system-prompt.md is read by no workflow; dispatch.yml assembles the prompt
# itself. Compiles a real pack, extracts the prompt `run:` block from
# dispatch.yml, runs it, and asserts allow and deny globs are in the result.
#
#   bash scripts/test-dispatch-write-scope.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/tmp" "$WORK/cp/role-packs/devops"
echo "charter" > "$WORK/cp/role-packs/devops/charter.md"
echo "conventions" > "$WORK/cp/CONVENTIONS.md"

python3 "$REPO_ROOT/compiler/compile-pack.py" --role devops --harness claude-code \
  --out "$WORK/pack" >/dev/null || exit 1

python3 - "$REPO_ROOT/.github/workflows/dispatch.yml" "$WORK/prompt.sh" <<'PY' || exit 1
import sys, yaml
wf = yaml.safe_load(open(sys.argv[1]))
for job in wf["jobs"].values():
    for step in job.get("steps", []):
        if step.get("name") == "Assemble the session prompt":
            open(sys.argv[2], "w").write(step["run"])
            sys.exit(0)
sys.exit("prompt step not found")
PY

printf '{"number":7,"state":"OPEN","title":"T","body":"B","updatedAt":"x","labels":[]}' \
  > "$WORK/tmp/issue.json"
export RUNNER_TEMP="$WORK/tmp" GITHUB_REPOSITORY=o/r GITHUB_STEP_SUMMARY="$WORK/summary" \
  GITHUB_OUTPUT="$WORK/out" ISSUE=7 ROLE=devops CP_DIR="$WORK/cp" PRODUCT_REPO=o/p \
  TURNS=1 COST_USD=1 TOKENS=1 WALL_CLOCK=1 BUDGET_SOURCE=t RUN_URL=u REQUIRES_PR=true \
  MATCHED_LABEL=status:ready PACK_DIR="$WORK/pack/devops/claude-code"
: > "$WORK/summary"
P="$WORK/tmp/session-prompt.md"

FAIL=0
ok() { if [ "$2" = 0 ]; then echo "  ok    $1"; else echo "  FAIL  $1"; FAIL=1; fi; }
has() { grep -qF -- "$1" "$P"; }

bash "$WORK/prompt.sh" >/dev/null 2>&1; ok "prompt builds" $?
has "# Write scope"; ok "has a write scope section" $?
has '- `.github/workflows/**`'; ok "lists an allowed path" $?
has '- `policies/**`'; ok "lists a denied path" $?
has '- `.github/CODEOWNERS`'; ok "lists the CODEOWNERS deny" $?

rm -f "$WORK/pack/devops/claude-code/write-scope.md" "$P"
bash "$WORK/prompt.sh" >/dev/null 2>&1; rc=$?
[ "$rc" != 0 ]; ok "no compiled write scope: fails closed" $?

[ "$FAIL" = 0 ] && echo "all passed" || { echo "FAILED"; exit 1; }
