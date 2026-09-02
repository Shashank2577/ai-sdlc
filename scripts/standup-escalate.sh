#!/usr/bin/env bash
# Apply needs-human to work items that have been status:blocked too long.
#
# Reads dashboards/standup.py's output rather than recomputing anything, so
# the digest and the escalations can never disagree: what the page says is
# blocked is exactly what gets flagged.
#
#   DIGEST=site/standup.json bash scripts/standup-escalate.sh
set -euo pipefail

DIGEST="${DIGEST:-dashboards/site/standup.json}"
RUN_URL="${RUN_URL:-}"
TMP="${RUNNER_TEMP:-/tmp}"

[ -f "$DIGEST" ] || { echo "standup-escalate: $DIGEST not found" >&2; exit 1; }

window=$(jq -r '.window_hours' "$DIGEST")
total=$(jq -r '.blocked_stale | length' "$DIGEST")

if [ "$total" -eq 0 ]; then
  echo "Nothing blocked beyond ${window}h. No escalations." \
    | tee -a "${GITHUB_STEP_SUMMARY:-/dev/null}"
  exit 0
fi

flagged=0
skipped=0

while read -r row; do
  [ -z "$row" ] && continue
  number=$(jq -r '.number' <<<"$row")
  hours=$(jq -r '.hours'  <<<"$row")
  since=$(jq -r '.since'  <<<"$row")

  if [ "$(jq -r '.already_flagged' <<<"$row")" = "true" ]; then
    echo "#${number}: blocked ${hours}h, needs-human already applied. Skipping."
    skipped=$((skipped + 1))
    continue
  fi

  note="${TMP}/blocked-${number}.md"
  {
    echo "### Escalation — blocked for ${hours}h"
    echo
    echo "This work item has carried \`status:blocked\` since \`${since}\`, which is"
    echo "past the ${window}h threshold. Blocked is a state with a deadline, not a"
    echo "resting place: past the threshold the assumption is that whatever it is"
    echo "waiting for is not going to arrive on its own."
    echo
    echo "**Goal:** unblock #${number} or take it off the board."
    echo
    echo "**What ran:** the standup digest, which derives this from the item's own"
    echo "\`labeled\` event history — not from anything an agent reported."
    echo
    echo "**Options**"
    echo
    echo "- **A — name the blocker and act on it.** If it is a dependency, link the"
    echo "  item it waits on. If it is a decision, make it here."
    echo "- **B — unblock by narrowing.** Cut the part that is blocked into its own"
    echo "  item and return the rest to \`status:ready\`."
    echo "- **C — drop it.** If it has been blocked this long and nothing broke,"
    echo "  the item may not be worth the slot it is holding."
    echo
    echo "**Recommendation:** A, unless nobody can name the blocker in one sentence"
    echo "— then it is really B or C."
    echo
    [ -n "$RUN_URL" ] && echo "Digest: ${RUN_URL}"
  } > "$note"

  gh issue comment "$number" --body-file "$note"
  gh issue edit "$number" --add-label "needs-human"
  echo "#${number}: blocked ${hours}h — needs-human applied."
  flagged=$((flagged + 1))
done < <(jq -c '.blocked_stale[]' "$DIGEST")

{
  echo "## Blocked-item escalations"
  echo
  echo "- ${flagged} flagged with \`needs-human\`"
  echo "- ${skipped} already flagged, left alone"
  echo "- threshold: ${window}h"
} >> "${GITHUB_STEP_SUMMARY:-/dev/null}"

echo "Escalated ${flagged}, skipped ${skipped} already-flagged."
