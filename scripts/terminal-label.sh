#!/usr/bin/env bash
# Terminal label — issue side. A closed issue must not keep a status:*
# label: status:* is the board's workflow state machine (CONVENTIONS.md),
# and "closed" is a fact that outranks any of them. scripts/sync-project.py
# already applies that rule to the board (desired_fields treats closed as
# outranking every label); this brings the same rule to the label itself,
# so the label and the board never disagree about whether work is done.
#
# status:blocked and needs-human survive a close — an item closed while
# flagged is worth a human noticing, not tidying away silently. qa:*
# verdicts are the audit trail and are never touched.
#
# Labels come from the issue-closed event payload (LABELS_JSON), not a
# `gh issue view` call, so a close that needs no change makes no gh calls
# at all. That matters because this fires on every close in the repository.
set -euo pipefail

: "${ISSUE:?}"
LABELS_JSON="${LABELS_JSON:-[]}"

mapfile -t stale < <(
  jq -r '.[].name | select(startswith("status:") and . != "status:blocked")' \
    <<<"$LABELS_JSON"
)

if [ "${#stale[@]}" -eq 0 ]; then
  echo "Issue #${ISSUE}: no stale status:* label. Nothing to do."
  exit 0
fi

for label in "${stale[@]}"; do
  gh issue edit "$ISSUE" --remove-label "$label"
done

echo "Issue #${ISSUE}: removed ${stale[*]} — closed is terminal, status:* does not outlive it."
