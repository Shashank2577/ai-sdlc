#!/usr/bin/env bash
# The dispatcher must build the agent prompt from the issue revision the
# guard validated (#232): an issue body edited after `status:ready` is
# applied must not reach the agent. Extracts the guard and prompt `run:`
# blocks from dispatch.yml and runs them against a stub `gh` whose issue
# body changes after its first read.
#
#   bash scripts/test-dispatch-prompt-snapshot.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bin" "$WORK/tmp" "$WORK/cp/role-packs/devops"
echo "charter" > "$WORK/cp/role-packs/devops/charter.md"

python3 - "$REPO_ROOT/.github/workflows/dispatch.yml" "$WORK" <<'PY' || exit 1
import sys, yaml
wf = yaml.safe_load(open(sys.argv[1]))
want = {"Guard — work item must be dispatchable for this role": "guard.sh",
        "Assemble the session prompt": "prompt.sh"}
for job in wf["jobs"].values():
    for step in job.get("steps", []):
        if step.get("name") in want:
            open(f"{sys.argv[2]}/{want.pop(step['name'])}", "w").write(step["run"])
sys.exit(f"steps not found: {list(want)}" if want else 0)
PY

# First `issue view` returns the approved revision; every later one, the edit.
cat > "$WORK/bin/gh" <<'STUB'
#!/usr/bin/env bash
if [ "$1" = "issue" ] && [ "$2" = "view" ]; then
  n=$(cat "$STATE" 2>/dev/null || echo 0); echo $((n+1)) > "$STATE"
  if [ "$n" = 0 ]; then body="APPROVED BODY"; else body="EDITED BODY"; fi
  printf '{"number":1,"state":"OPEN","title":"T","body":"%s","updatedAt":"x","labels":[{"name":"status:ready"}]}' "$body"
fi
STUB
chmod +x "$WORK/bin/gh"
mkdir -p "$WORK/pack"; echo "# Write scope" > "$WORK/pack/write-scope.md"
export PATH="$WORK/bin:$PATH" STATE="$WORK/state" RUNNER_TEMP="$WORK/tmp" \
  GITHUB_REPOSITORY=o/r GITHUB_STEP_SUMMARY="$WORK/summary" GITHUB_OUTPUT="$WORK/out" \
  ISSUE=1 ROLE=devops ACCEPTED=status:ready PACK_DIR="$WORK/pack" CP_DIR="$WORK/cp" PRODUCT_REPO=o/p \
  TURNS=1 COST_USD=1 TOKENS=1 WALL_CLOCK=1 BUDGET_SOURCE=t RUN_URL=u REQUIRES_PR=true
: > "$WORK/summary"

FAIL=0
ok() { if [ "$2" = 0 ]; then echo "  ok    $1"; else echo "  FAIL  $1"; FAIL=1; fi; }

bash "$WORK/guard.sh" >/dev/null 2>&1; ok "guard passes" $?
bash "$WORK/prompt.sh" >/dev/null 2>&1
P="$WORK/tmp/session-prompt.md"
grep -qF "APPROVED BODY" "$P"; ok "prompt uses the approved (pre-edit) body" $?
! grep -qF "EDITED BODY" "$P"; ok "prompt never contains the post-edit body" $?

rm -f "$WORK/tmp/issue.json" "$P"
bash "$WORK/prompt.sh" >/dev/null 2>&1; rc=$?
[ "$rc" != 0 ] && [ ! -e "$P" ]; ok "no snapshot: fails closed, no live fetch" $?

[ "$FAIL" = 0 ] && echo "all passed" || { echo "FAILED"; exit 1; }
