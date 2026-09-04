#!/usr/bin/env bash
# DoD check v0 — implements the enforced subset of policies/dod.yaml.
# Runs on every pull request. Fails with a PR comment listing exactly
# what is missing, so an agent (or a human) can fix without guessing.
set -euo pipefail

: "${BASE_SHA:?}" "${HEAD_SHA:?}" "${PR_NUMBER:?}"

failures=()
required=(Work-Item Requirement Agent-Role Harness)

# 1. Every non-merge commit on the PR carries the four trailers.
# Git only recognizes the final contiguous block of the message as
# trailers — a blank line anywhere in that block (e.g. before a
# harness-appended `Co-authored-by:`) knocks everything above the blank
# line back into ordinary body text. A required trailer can therefore be
# visible in `git log` and still be invisible to `%(trailers:only,unfold)`.
# Distinguish that case ("present but outside the block") from a trailer
# that never appears at all, since the fix for each is different.
while read -r sha; do
  [ -z "$sha" ] && continue
  trailers=$(git log -1 --format='%(trailers:only,unfold)' "$sha")
  subject=$(git log -1 --format='%s' "$sha")
  body=$(git log -1 --format='%B' "$sha")
  for t in "${required[@]}"; do
    if grep -qi "^${t}:" <<<"$trailers"; then
      continue
    fi
    if grep -qi "^${t}:" <<<"$body"; then
      failures+=("commit \`${sha:0:7}\` (\"${subject}\") has a \`${t}:\` line in the message, but it is outside the trailer block git recognizes — it is being read as body text, not a trailer. Trailers must form one contiguous block at the end of the commit message, after any appended \`Co-authored-by:\` line; a blank line anywhere in that block (often the one left before an appended \`Co-authored-by:\`) splits it, and everything above the split stops counting.")
    else
      failures+=("commit \`${sha:0:7}\` (\"${subject}\") is missing trailer \`${t}:\`")
    fi
  done
done < <(git rev-list --no-merges "$BASE_SHA..$HEAD_SHA")

# 2. PR body closes a work item with a GitHub closing keyword (or opts out
#    explicitly, per policies/dod.yaml's linked_work_item.opt_out) and has no
#    unchecked DoD boxes. The closing-keyword regex is qa-gate.sh's — same
#    rule, reused rather than rewritten, per #91/#92.
body=$(gh pr view "$PR_NUMBER" --json body --jq '.body // ""')
closing_ref=$(grep -Eoi '\b(close[sd]?|fix(e[sd])?|resolve[sd]?)[[:space:]]+#[0-9]+' <<<"$body" || true)
opt_out=$(grep -E 'Relates to #[0-9]+ — it does not close it' <<<"$body" || true)
if [ -z "$closing_ref" ] && [ -z "$opt_out" ]; then
  if grep -Eq '#[0-9]+' <<<"$body"; then
    failures+=("PR body mentions an issue but has no GitHub closing keyword — write \`Closes #<issue>\` (Fixes/Resolves also work) so the work item closes on merge, or, if this PR deliberately closes nothing, use the opt-out phrase \`Relates to #<issue> — it does not close it\`")
  else
    failures+=("PR body has no linked work item — write \`Closes #<issue>\` (Fixes/Resolves also work), or the opt-out phrase \`Relates to #<issue> — it does not close it\` if this PR deliberately closes nothing")
  fi
fi
# Fenced code blocks are stripped first. A PR demonstrating a tool that
# reads acceptance criteria has to *show* those criteria, and an unticked
# box inside a ``` fence is quoted evidence, not an outstanding DoD item.
# #172 — the PR adding scripts/check-story-scope.py — failed its own DoD
# for pasting the input it feeds the checker.
# Fenced blocks first, then inline `code` spans. Both are quotation.
# The PR that added the fenced-block strip failed on its own body for
# writing the literal in backticks while explaining the bug — so inline
# spans are the same problem wearing different punctuation.
prose=$(awk 'BEGIN{f=0} /^[[:space:]]*```/{f=!f; next} !f{print}' <<<"$body" \
          | sed 's/`[^`]*`//g')
if grep -Fq -- '- [ ]' <<<"$prose"; then
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

msg="DoD check passed: trailers on all commits, work item linked with a closing keyword (or opt-out), checklist complete."
echo "$msg" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
echo "$msg"
