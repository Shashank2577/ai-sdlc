#!/usr/bin/env bash
# Security gate — PR side. A pull request cannot merge while any work item it
# closes carries security:rejected.
#
# This is half of the veto ADR-0008 proposes and #216 wires. Without it,
# `Closes #N` would let a merge close a security-rejected story out from
# under the reviewer. The other half is scripts/security-verdict.sh, which
# reopens a rejected item closed by hand.
#
# Mirrors scripts/qa-gate.sh exactly, s/qa/security/.
set -euo pipefail

: "${PR_NUMBER:?}"

body=$(gh pr view "$PR_NUMBER" --json body --jq '.body // ""')

# GitHub's own closing keywords, matched the way GitHub matches them.
linked=$(
  grep -Eoi '\b(close[sd]?|fix(e[sd])?|resolve[sd]?)[[:space:]]+#[0-9]+' <<<"$body" \
    | grep -Eo '[0-9]+' | sort -un || true
)

if [ -z "$linked" ]; then
  msg="Security gate: this PR closes no work item, so there is no verdict to honour."
  echo "$msg" | tee -a "${GITHUB_STEP_SUMMARY:-/dev/null}"
  exit 0
fi

blocked=()
checked=()
for issue in $linked; do
  labels=$(gh issue view "$issue" --json labels --jq '[.labels[].name] | join(" ")' 2>/dev/null || echo "")
  checked+=("#${issue}")
  case " $labels " in
    *" security:rejected "*) blocked+=("$issue") ;;
  esac
done

report="${RUNNER_TEMP:-/tmp}/security-gate.md"

if [ "${#blocked[@]}" -eq 0 ]; then
  msg="Security gate passed: ${checked[*]} carry no security:rejected verdict."
  echo "$msg" | tee -a "${GITHUB_STEP_SUMMARY:-/dev/null}"
  exit 0
fi

{
  echo "## Security gate failed"
  echo
  echo "This pull request closes a work item that security has rejected. The"
  echo "verdict is binding — merging would close a story security said is not"
  echo "safe to ship."
  echo
  for issue in "${blocked[@]}"; do
    echo "- #${issue} carries \`security:rejected\`"
  done
  echo
  echo "Two ways forward, both deliberate:"
  echo
  echo "1. **Fix what security found**, push, and have security re-review. The"
  echo "   verdict flips to \`security:approved\` and this check goes green on"
  echo "   the next run."
  echo "2. **Overrule the verdict** by removing the \`security:rejected\` label."
  echo "   That needs write access, so it is a human decision, on the record,"
  echo "   in the issue's event history."
  echo
  echo "Policy of record: \`role-packs/security/policy.yaml\` (\`verdict.intended_to_block_closure\`)."
} > "$report"

cat "$report"
cat "$report" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
gh pr comment "$PR_NUMBER" --body-file "$report" || true
exit 1
