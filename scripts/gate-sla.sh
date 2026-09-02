#!/usr/bin/env bash
# Enforce the approval-gate SLA (policies/gates.yaml: sla_hours,
# escalates_after_sla). A silent gate must not stall the board forever.
#
# For each open issue carrying `needs-human` and `status:needs-refinement`,
# read how long `needs-human` has been applied from the issue's own
# `labeled` events — not `updatedAt`, which a daily comment resets without
# the wait actually ending. Past sla_hours, post one comment naming the
# wait. Keyed on the comment's own marker rather than the label, so a
# daily run never re-comments — same idea as scripts/standup-escalate.sh,
# applied to the SLA rather than the blocked-item escalation.
#
#   GH_REPO=owner/repo bash scripts/gate-sla.sh
set -euo pipefail

GATES="${GATES_FILE:-policies/gates.yaml}"
TMP="${RUNNER_TEMP:-/tmp}"
RUN_URL="${RUN_URL:-}"
MARKER="<!-- gate-sla:notice -->"
NEEDS_HUMAN="needs-human"
NEEDS_REFINEMENT="status:needs-refinement"

: "${GH_REPO:?gate-sla: GH_REPO must be set}"
[ -f "$GATES" ] || { echo "gate-sla: $GATES not found" >&2; exit 1; }

sla_hours=$(grep -m1 -E '^[[:space:]]*sla_hours:' "$GATES" \
  | sed -E 's/^[^:]*:[[:space:]]*([0-9]+).*/\1/')
[ -n "$sla_hours" ] || { echo "gate-sla: sla_hours not found in $GATES" >&2; exit 1; }

now_epoch=$(date -u -d "${NOW:-now}" +%s)

candidates=$(gh issue list --state open --label "$NEEDS_HUMAN" \
  --json number,title,url,labels)

total=$(jq --arg lbl "$NEEDS_REFINEMENT" \
  '[.[] | select(.labels | any(.name == $lbl))] | length' <<<"$candidates")

if [ "$total" -eq 0 ]; then
  echo "gate-sla: no open issue is both ${NEEDS_HUMAN} and ${NEEDS_REFINEMENT}. Nothing to do." \
    | tee -a "${GITHUB_STEP_SUMMARY:-/dev/null}"
  exit 0
fi

posted=0
skipped=0

while read -r issue; do
  [ -z "$issue" ] && continue
  number=$(jq -r '.number' <<<"$issue")

  events=$(gh api --paginate "repos/${GH_REPO}/issues/${number}/events" \
    --jq "[.[] | select(.event == \"labeled\" and .label.name == \"${NEEDS_HUMAN}\") | .created_at]")
  since=$(jq -r 'if length == 0 then "" else max end' <<<"$events")
  if [ -z "$since" ]; then
    echo "#${number}: no ${NEEDS_HUMAN} labeled event found. Skipping."
    continue
  fi

  since_epoch=$(date -u -d "$since" +%s)
  hours=$(( (now_epoch - since_epoch) / 3600 ))

  if [ "$hours" -lt "$sla_hours" ]; then
    echo "#${number}: waiting ${hours}h, under the ${sla_hours}h SLA. Nothing to do."
    continue
  fi

  comments=$(gh issue view "$number" --json comments --jq '[.comments[].body] | join("\n")')
  if grep -qF -- "$MARKER" <<<"$comments"; then
    echo "#${number}: SLA comment already posted. Skipping."
    skipped=$((skipped + 1))
    continue
  fi

  note="${TMP}/gate-sla-${number}.md"
  {
    echo "### Approval gate — SLA passed"
    echo
    echo "This story has carried \`${NEEDS_HUMAN}\` for **${hours}h**, past the"
    echo "\`${sla_hours}h\` SLA in \`policies/gates.yaml\`. The dispatch-approval"
    echo "gate is still waiting on a person."
    echo
    echo "**To approve:** apply \`status:ready\` yourself."
    echo "**To keep holding it:** do nothing — it stays on \`${NEEDS_REFINEMENT}\`."
    echo
    [ -n "$RUN_URL" ] && echo "Run: ${RUN_URL}"
    echo
    echo "$MARKER"
  } > "$note"

  gh issue comment "$number" --body-file "$note"
  echo "#${number}: waited ${hours}h — SLA comment posted."
  posted=$((posted + 1))
done < <(jq -c --arg lbl "$NEEDS_REFINEMENT" \
  '.[] | select(.labels | any(.name == $lbl))' <<<"$candidates")

{
  echo "## Approval-gate SLA"
  echo
  echo "- ${posted} SLA comment(s) posted"
  echo "- ${skipped} already noted, left alone"
  echo "- SLA: ${sla_hours}h"
} >> "${GITHUB_STEP_SUMMARY:-/dev/null}"

echo "gate-sla: ${posted} posted, ${skipped} already noted."
