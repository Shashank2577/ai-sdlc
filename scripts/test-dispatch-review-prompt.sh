#!/usr/bin/env bash
# A dispatch from status:in-review is a review of a change that already
# exists (#292). Extracts the prompt `run:` block from dispatch.yml and runs
# it against a stub `gh`: a review dispatch must name the pull request and
# must not tell the session to branch, commit, push or open a PR; any other
# dispatch keeps the implementation prompt.
#
#   bash scripts/test-dispatch-review-prompt.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bin" "$WORK/tmp" "$WORK/cp/role-packs/qa" "$WORK/cp/role-packs/developer"
echo "charter" > "$WORK/cp/role-packs/qa/charter.md"
echo "charter" > "$WORK/cp/role-packs/developer/charter.md"
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

# `gh pr list` prints $PR_LIST (or fails when PR_LIST_FAIL=1); nothing else
# is expected to reach the network from this step.
cat > "$WORK/bin/gh" <<'STUB'
#!/usr/bin/env bash
if [ "$1" = "pr" ] && [ "$2" = "list" ]; then
  if [ "${PR_LIST_FAIL:-0}" = 1 ]; then echo "HTTP 502" >&2; exit 1; fi
  printf '%s' "$PR_LIST"
  exit 0
fi
echo "unexpected gh call: $*" >&2; exit 1
STUB
chmod +x "$WORK/bin/gh"

printf '{"number":7,"state":"OPEN","title":"T","body":"Build the thing.","updatedAt":"x","labels":[]}' \
  > "$WORK/tmp/issue.json"

export PATH="$WORK/bin:$PATH" RUNNER_TEMP="$WORK/tmp" GITHUB_REPOSITORY=o/r \
  GITHUB_STEP_SUMMARY="$WORK/summary" GITHUB_OUTPUT="$WORK/out" ISSUE=7 \
  CP_DIR="$WORK/cp" PRODUCT_REPO=o/p TURNS=1 COST_USD=1 TOKENS=1 WALL_CLOCK=1 \
  BUDGET_SOURCE=t RUN_URL=u REQUIRES_PR=true \
  PR_LIST='[{"number":12,"title":"fix: the thing","url":"https://x/pull/12","headRefName":"bug/FDY-7-the-thing","state":"OPEN"},
            {"number":13,"title":"other","url":"https://x/pull/13","headRefName":"bug/FDY-70-other","state":"OPEN"}]'
: > "$WORK/summary"
P="$WORK/tmp/session-prompt.md"

FAIL=0
ok() { if [ "$2" = 0 ]; then echo "  ok    $1"; else echo "  FAIL  $1"; FAIL=1; fi; }
has() { grep -qF -- "$1" "$P"; }

echo "review dispatch (qa from status:in-review)"
ROLE=qa MATCHED_LABEL=status:in-review bash "$WORK/prompt.sh" >/dev/null 2>"$WORK/err"; ok "prompt builds" $?
has "## Pull request under review"; ok "has a pull-request-under-review section" $?
has "#12 (OPEN) fix: the thing"; ok "names this item's PR" $?
! has "https://x/pull/13"; ok "does not name FDY-70's PR for item 7" $?
has "Do not build the work item again"; ok "says not to re-implement" $?
has "do not branch,"; ok "says not to branch, commit or push" $?
! has "commit, push and open your pull request here"; ok "drops the implementation instruction" $?
! has "land a correct, small change and open the PR"; ok "drops the open-a-PR budget advice" $?

echo "review dispatch, PR lookup fails"
ROLE=qa MATCHED_LABEL=status:in-review PR_LIST_FAIL=1 bash "$WORK/prompt.sh" >/dev/null 2>&1; ok "prompt still builds" $?
has "The lookup failed (HTTP 502"; ok "says the lookup failed, not that no PR exists" $?
! has "_None found"; ok "does not claim there is no PR" $?

echo "review dispatch, no PR exists"
ROLE=qa MATCHED_LABEL=status:in-review PR_LIST='[]' bash "$WORK/prompt.sh" >/dev/null 2>&1; ok "prompt builds" $?
has "_None found on a"; ok "says none was found" $?

echo "implementation dispatch (developer from status:ready)"
ROLE=developer MATCHED_LABEL=status:ready bash "$WORK/prompt.sh" >/dev/null 2>&1; ok "prompt builds" $?
has "commit, push and open your pull request here"; ok "keeps the implementation instruction" $?
has "land a correct, small change and open the PR"; ok "keeps the budget advice" $?
! has "## Pull request under review"; ok "has no review section" $?

[ "$FAIL" = 0 ] && echo "all passed" || { echo "FAILED"; exit 1; }
