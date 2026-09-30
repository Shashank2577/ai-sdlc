#!/usr/bin/env bash
# The prompt a dispatched session receives must state the role's write
# scope, allow and deny (#233). Extracts the prompt `run:` block from
# dispatch.yml and runs it against a fake control plane.
#
#   bash scripts/test-dispatch-write-scope-prompt.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/tmp" "$WORK/cp/role-packs/r"
echo "charter" > "$WORK/cp/role-packs/r/charter.md"
echo "conventions" > "$WORK/cp/CONVENTIONS.md"

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

printf '{"number":7,"state":"OPEN","title":"T","body":"Build.","updatedAt":"x","labels":[]}' \
  > "$WORK/tmp/issue.json"
export RUNNER_TEMP="$WORK/tmp" GITHUB_REPOSITORY=o/r GITHUB_STEP_SUMMARY="$WORK/summary" \
  GITHUB_OUTPUT="$WORK/out" ISSUE=7 CP_DIR="$WORK/cp" PRODUCT_REPO=o/p TURNS=1 \
  COST_USD=1 TOKENS=1 WALL_CLOCK=1 BUDGET_SOURCE=t RUN_URL=u REQUIRES_PR=true \
  ROLE=r MATCHED_LABEL=status:ready
P="$WORK/tmp/session-prompt.md"

FAIL=0
ok() { if [ "$2" = 0 ]; then echo "  ok    $1"; else echo "  FAIL  $1"; FAIL=1; fi; }
has() { grep -qF -- "$1" "$P"; }

echo "policy with a write scope"
cat > "$WORK/cp/role-packs/r/policy.yaml" <<'Y'
write_scope:
  allow: ["docs/**", "infra/**"]
  deny: ["src/**"]
Y
bash "$WORK/prompt.sh" >/dev/null 2>&1; ok "prompt builds" $?
has "## Write scope"; ok "has a write scope section" $?
has '- `docs/**`'; ok "lists an allow pattern" $?
has '- `infra/**`'; ok "lists every allow pattern" $?
has '- `src/**`'; ok "lists the deny pattern" $?

echo "malformed write scope"
printf 'write_scope: {allow: "docs/**"}\n' > "$WORK/cp/role-packs/r/policy.yaml"
bash "$WORK/prompt.sh" >/dev/null 2>&1; [ $? -ne 0 ]; ok "step fails rather than omit the scope" $?

[ "$FAIL" = 0 ] && echo "all passed" || { echo "FAILED"; exit 1; }
