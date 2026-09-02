#!/usr/bin/env bash
# QA gate — PR side. A pull request cannot merge while any work item it
# closes carries qa:rejected.
#
# This is half of the veto in PRD §3 / REQ-009. Without it, `Closes #N`
# would let a merge close a rejected story out from under QA. The other
# half is scripts/qa-verdict.sh, which reopens a rejected item closed by
# hand.
set -euo pipefail

: "${PR_NUMBER:?}"

body=$(gh pr view "$PR_NUMBER" --json body --jq '.body // ""')

# GitHub's own closing keywords, matched the way GitHub matches them.
linked=$(
  grep -Eoi '\b(close[sd]?|fix(e[sd])?|resolve[sd]?)[[:space:]]+#[0-9]+' <<<"$body" \
    | grep -Eo '[0-9]+' | sort -un || true
)

if [ -z "$linked" ]; then
  msg="QA gate: this PR closes no work item, so there is no verdict to honour."
  echo "$msg" | tee -a "${GITHUB_STEP_SUMMARY:-/dev/null}"
  exit 0
fi

blocked=()
checked=()
for issue in $linked; do
  labels=$(gh issue view "$issue" --json labels --jq '[.labels[].name] | join(" ")' 2>/dev/null || echo "")
  checked+=("#${issue}")
  case " $labels " in
    *" qa:rejected "*) blocked+=("$issue") ;;
  esac
done

report="${RUNNER_TEMP:-/tmp}/qa-gate.md"

if [ "${#blocked[@]}" -eq 0 ]; then
  msg="QA gate passed: ${checked[*]} carry no qa:rejected verdict."
  echo "$msg" | tee -a "${GITHUB_STEP_SUMMARY:-/dev/null}"
  exit 0
fi

{
  echo "## QA gate failed"
  echo
  echo "This pull request closes a work item that QA has rejected. The verdict"
  echo "is binding — merging would close a story QA said is not done."
  echo
  for issue in "${blocked[@]}"; do
    echo "- #${issue} carries \`qa:rejected\`"
  done
  echo
  echo "Two ways forward, both deliberate:"
  echo
  echo "1. **Fix what QA found**, push, and have QA re-review. The verdict flips"
  echo "   to \`qa:approved\` and this check goes green on the next run."
  echo "2. **Overrule the verdict** by removing the \`qa:rejected\` label. That"
  echo "   needs write access, so it is a human decision, on the record, in the"
  echo "   issue's event history."
  echo
  echo "Policy of record: \`role-packs/qa/policy.yaml\` (\`verdict.blocks_closure\`)."
} > "$report"

cat "$report"
cat "$report" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
gh pr comment "$PR_NUMBER" --body-file "$report" || true
exit 1
