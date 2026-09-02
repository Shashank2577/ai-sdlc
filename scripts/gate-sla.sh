#!/usr/bin/env bash
# Enforce the approval-gate SLA (policies/gates.yaml: gates.dispatch_approval).
#
# scripts/gate-check.py already holds a critical story on `needs-human` +
# `status:needs-refinement` when an agent cannot get it approved. This does
# not re-decide that; it only measures how long the hold has sat unanswered
# and, past the policy's sla_hours, posts one comment naming the wait — a
# silent gate must not be able to stall a story indefinitely (REQ-007).
#
# Wait is read from the issue's own `labeled` events for `needs-human`,
# never `updatedAt`: an item commented on daily can still have waited the
# whole time. dashboards/standup.py:collect_blocked_since is the same query
# shape, one label over.
#
# There is no second label to flip here — needs-human is already applied.
# Idempotency is keyed on the SLA comment itself: scripts/standup-escalate.sh
# checks a flag before acting so a daily run doesn't re-comment on the same
# item forever; this checks for its own marker comment instead.
#
#   GH_TOKEN=... bash scripts/gate-sla.sh
set -euo pipefail

: "${GITHUB_REPOSITORY:?}"
GATES="${GATES_POLICY:-policies/gates.yaml}"
RUN_URL="${RUN_URL:-}"
MARKER="<!-- gate-sla:dispatch_approval -->"

# The policy file is the source of truth for the threshold, not this
# script — read it live so a changed sla_hours takes effect with no code
# change (CONVENTIONS.md: the policy wins if the two ever disagree).
SLA_HOURS="${SLA_HOURS:-}"
if [ -z "$SLA_HOURS" ] && [ -f "$GATES" ]; then
  SLA_HOURS=$(awk '/^[[:space:]]*sla_hours:[[:space:]]*[0-9]+/ {print $2; exit}' "$GATES")
fi
SLA_HOURS="${SLA_HOURS:-24}"

candidates=$(gh issue list --state open \
  --label "needs-human" --label "status:needs-refinement" \
  --json number,title,url)

total=$(jq 'length' <<<"$candidates")
if [ "$total" -eq 0 ]; then
  echo "No story held on needs-human + status:needs-refinement. Nothing to do."
  exit 0
fi

now_epoch=$(date -u +%s)
posted=0
skipped=0

while read -r row; do
  [ -z "$row" ] && continue
  number=$(jq -r '.number' <<<"$row")

  since=$(gh api --paginate "repos/${GITHUB_REPOSITORY}/issues/${number}/events" \
    --jq '[.[] | select(.event == "labeled" and .label.name == "needs-human") | .created_at] | max')

  if [ -z "$since" ] || [ "$since" = "null" ]; then
    echo "#${number}: no needs-human labeled event on record. Skipping."
    continue
  fi

  since_epoch=$(date -u -d "$since" +%s)
  hours=$(awk -v a="$now_epoch" -v b="$since_epoch" 'BEGIN{printf "%.1f", (a - b) / 3600}')

  if ! awk -v h="$hours" -v s="$SLA_HOURS" 'BEGIN{exit !(h > s)}'; then
    echo "#${number}: waiting ${hours}h, within the ${SLA_HOURS}h SLA."
    continue
  fi

  already=$(gh issue view "$number" --json comments \
    --jq "[.comments[].body // \"\"] | any(contains(\"${MARKER}\"))")
  if [ "$already" = "true" ]; then
    echo "#${number}: waiting ${hours}h, SLA comment already posted. Skipping."
    skipped=$((skipped + 1))
    continue
  fi

  note="${RUNNER_TEMP:-/tmp}/gate-sla-${number}.md"
  {
    echo "$MARKER"
    echo "### Approval-gate SLA exceeded"
    echo
    echo "This story has waited on \`needs-human\` for approval since"
    echo "\`${since}\` — ${hours}h, past the ${SLA_HOURS}h SLA that"
    echo "\`policies/gates.yaml\` sets for the dispatch-approval gate."
    echo
    echo "It stays on \`status:needs-refinement\` until a person applies"
    echo "\`status:ready\` themselves — that is the gate's own default for"
    echo "an unanswered decision, not a change this comment is making."
    if [ -n "$RUN_URL" ]; then
      echo
      echo "Run: ${RUN_URL}"
    fi
  } > "$note"

  gh issue comment "$number" --body-file "$note"
  echo "#${number}: waiting ${hours}h — SLA comment posted."
  posted=$((posted + 1))
done < <(jq -c '.[]' <<<"$candidates")

{
  echo "## Approval-gate SLA"
  echo
  echo "- ${posted} SLA comment(s) posted"
  echo "- ${skipped} already flagged, left alone"
  echo "- threshold: ${SLA_HOURS}h"
} >> "${GITHUB_STEP_SUMMARY:-/dev/null}"

echo "Approval-gate SLA: ${posted} posted, ${skipped} already posted, threshold ${SLA_HOURS}h."
