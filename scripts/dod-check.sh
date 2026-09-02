#!/usr/bin/env bash
# DoD check v0 — implements the enforced subset of policies/dod.yaml.
# Runs on every pull request. Fails with a PR comment listing exactly
# what is missing, so an agent (or a human) can fix without guessing.
set -euo pipefail

: "${BASE_SHA:?}" "${HEAD_SHA:?}" "${PR_NUMBER:?}"

failures=()
required=(Work-Item Requirement Agent-Role Harness)

# 1. Every non-merge commit on the PR carries the four trailers.
while read -r sha; do
  [ -z "$sha" ] && continue
  trailers=$(git log -1 --format='%(trailers:only,unfold)' "$sha")
  subject=$(git log -1 --format='%s' "$sha")
  for t in "${required[@]}"; do
    if ! grep -qi "^${t}:" <<<"$trailers"; then
      failures+=("commit \`${sha:0:7}\` (\"${subject}\") is missing trailer \`${t}:\`")
    fi
  done
done < <(git rev-list --no-merges "$BASE_SHA..$HEAD_SHA")

# 2. PR body links a work item and has no unchecked DoD boxes.
body=$(gh pr view "$PR_NUMBER" --json body --jq '.body // ""')
if ! grep -Eq '#[0-9]+' <<<"$body"; then
  failures+=("PR body has no linked work item (expected an \`#<issue>\` reference)")
fi
if grep -Fq -- '- [ ]' <<<"$body"; then
  failures+=("PR body has unchecked Definition of Done items")
fi

# 3. Verdict.
if [ "${#failures[@]}" -gt 0 ]; then
  {
    echo "## DoD check failed"
    echo ""
    printf -- '- %s\n' "${failures[@]}"
    echo ""
    echo "Policy of record: \`policies/dod.yaml\` (enforced v0 subset). Fix and push; this check re-runs."
  } > /tmp/dod-report.md
  cat /tmp/dod-report.md >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
  cat /tmp/dod-report.md
  gh pr comment "$PR_NUMBER" --body-file /tmp/dod-report.md || true
  exit 1
fi

msg="DoD check passed: trailers on all commits, work item linked, checklist complete."
echo "$msg" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
echo "$msg"
