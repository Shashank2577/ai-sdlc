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
pr_req_ids=()
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
  # Collect this PR's own Requirement ids as we walk anyway, for the
  # deferral check below (policies/dod.yaml: requires_matching_requirement).
  req_line=$(grep -i '^Requirement:' <<<"$trailers" || true)
  [ -z "$req_line" ] && req_line=$(grep -i '^Requirement:' <<<"$body" || true)
  while read -r rid; do
    [ -n "$rid" ] && pr_req_ids+=("$rid")
  done < <(grep -Eo 'REQ-[0-9]+' <<<"$req_line")
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
# Anchored to line start. A checklist item is only a checklist item at the
# beginning of a line — mid-sentence it is prose about one. Stripping
# quotation is not enough on its own: an inline code span wrapped across
# two lines survives the line-based sed above, which is how this very PR
# failed its own check while documenting the form it adds.
if grep -Eq '^[[:space:]]*- \[ \]' <<<"$prose"; then
  failures+=("PR body has unchecked Definition of Done items")
fi

# `- [~]` deferral form (policies/dod.yaml: checklist_complete.deferral).
# It is not a third state that always passes: it counts as resolved only
# when the line names a real, open issue and states a reason, and that
# issue's body carries one of this PR's own Requirement ids. Anything
# short of that fails exactly as a plain unticked box does — the form
# lives in the policy file; this only checks a PR body against it.
while IFS= read -r line; do
  # Same anchoring as the unticked check above, for the same reason.
  case "$line" in
    ' - [~]'*|'- [~]'*|'  - [~]'*|'   - [~]'*|'    - [~]'*) ;;
    *) continue ;;
  esac
  if [[ "$line" =~ deferred[[:space:]]+to[[:space:]]+#([0-9]+):[[:space:]]*(.*)$ ]]; then
    issue_num="${BASH_REMATCH[1]}"
    reason="$(sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//' <<<"${BASH_REMATCH[2]}")"
    if [ -z "$reason" ]; then
      failures+=("deferred item states no reason after \`deferred to #${issue_num}:\`: \`${line}\`")
      continue
    fi
    issue_json=$(gh issue view "$issue_num" --json state,body 2>/dev/null || true)
    if [ -z "$issue_json" ]; then
      failures+=("deferred item points at #${issue_num}, which does not exist: \`${line}\`")
      continue
    fi
    issue_state=$(jq -r '.state' <<<"$issue_json")
    if [ "$issue_state" != "OPEN" ]; then
      failures+=("deferred item points at #${issue_num}, which is not open (state: ${issue_state}): \`${line}\`")
      continue
    fi
    if [ "${#pr_req_ids[@]}" -eq 0 ]; then
      failures+=("deferred item points at #${issue_num}, but this PR carries no Requirement id to match it against: \`${line}\`")
      continue
    fi
    issue_body=$(jq -r '.body // ""' <<<"$issue_json")
    matched=0
    for req in "${pr_req_ids[@]}"; do
      if grep -qE "\\b${req}\\b" <<<"$issue_body"; then
        matched=1
        break
      fi
    done
    if [ "$matched" -eq 0 ]; then
      failures+=("deferred item points at #${issue_num}, whose body names none of this PR's Requirement ids ($(printf '%s ' "${pr_req_ids[@]}")): \`${line}\`")
    fi
  else
    failures+=("deferred item does not match the required form \`- [~] <criterion> — deferred to #<issue>: <reason>\`: \`${line}\`")
  fi
done <<<"$prose"

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
