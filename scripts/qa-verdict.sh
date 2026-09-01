#!/usr/bin/env bash
# QA verdict enforcement — issue side. Two modes, driven by the event that
# fired the workflow.
#
#   close-guard  a rejected work item that gets closed is reopened
#   ladder       the third qa:rejected on one item escalates to a human
#
# Rejection counts come from the tracker's own `labeled` timeline events,
# never from anything an agent reports. Event-derived, per REQ-006.
set -euo pipefail

: "${MODE:?}" "${ISSUE:?}" "${GITHUB_REPOSITORY:?}"
RUN_URL="${RUN_URL:-}"
TMP="${RUNNER_TEMP:-/tmp}"

# The policy file is the source of truth for the threshold, not the
# workflow. CONVENTIONS.md: if the policy and the script disagree, the
# policy wins — so read it rather than restating it.
POLICY="${QA_POLICY:-role-packs/qa/policy.yaml}"
if [ -z "${THRESHOLD:-}" ] && [ -f "$POLICY" ]; then
  THRESHOLD=$(awk '/^[[:space:]]*rejection_escalation_threshold:[[:space:]]*[0-9]+/ {print $2; exit}' "$POLICY")
fi
THRESHOLD="${THRESHOLD:-3}"

has_label() {
  gh issue view "$ISSUE" --json labels --jq \
    "[.labels[].name] | index(\"$1\") != null" 2>/dev/null | grep -q true
}

# Every time qa:rejected was applied, from the issue's event history.
count_rejections() {
  gh api --paginate "repos/${GITHUB_REPOSITORY}/issues/${ISSUE}/events" \
    --jq '.[] | select(.event == "labeled" and .label.name == "qa:rejected") | .created_at' \
    2>/dev/null | grep -c . || true
}

case "$MODE" in

  close-guard)
    if ! has_label "qa:rejected"; then
      echo "Issue #${ISSUE} closed without a qa:rejected verdict. Nothing to do."
      exit 0
    fi

    report="${TMP}/close-guard.md"
    {
      echo "### Reopened — QA verdict is binding"
      echo
      echo "This work item carries \`qa:rejected\`, so it cannot be closed. A"
      echo "rejected story that quietly closes is the one failure the QA veto"
      echo "exists to prevent, so the automation reopens it rather than"
      echo "trusting the close."
      echo
      echo "To close it, one of:"
      echo
      echo "1. Fix what QA found and have QA re-review — the verdict flips to"
      echo "   \`qa:approved\` and closure is unblocked."
      echo "2. Remove the \`qa:rejected\` label first. That takes write access,"
      echo "   so overruling QA is a human decision recorded in the event log."
      echo
      [ -n "$RUN_URL" ] && echo "Run: ${RUN_URL}"
      echo
      echo "Policy of record: \`role-packs/qa/policy.yaml\` (\`verdict.blocks_closure\`)."
    } > "$report"

    gh issue reopen "$ISSUE" --comment "$(cat "$report")"
    cat "$report" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
    echo "Issue #${ISSUE} reopened: qa:rejected blocks closure."
    ;;

  ladder)
    rejections=$(count_rejections)
    echo "Issue #${ISSUE}: ${rejections} qa:rejected event(s), threshold ${THRESHOLD}."

    if [ "$rejections" -lt "$THRESHOLD" ]; then
      echo "Below threshold. The loop is still converging; no escalation." \
        | tee -a "${GITHUB_STEP_SUMMARY:-/dev/null}"
      exit 0
    fi

    if has_label "needs-human"; then
      echo "Already escalated — needs-human is present. Not commenting again." \
        | tee -a "${GITHUB_STEP_SUMMARY:-/dev/null}"
      exit 0
    fi

    report="${TMP}/ladder.md"
    {
      echo "### Escalation — ${rejections} QA rejections on one work item"
      echo
      echo "QA has rejected this item ${rejections} times. Past the threshold of"
      echo "${THRESHOLD}, the assumption changes: three rejections is rarely three"
      echo "unrelated mistakes, it is usually a work item that was wrong from the"
      echo "start and that everyone has been patching around."
      echo
      echo "**Goal:** deliver #${ISSUE} to its stated acceptance criteria."
      echo
      echo "**What ran:** ${rejections} developer→QA cycles. Each rejection comment"
      echo "is above, with the criteria table that produced it."
      echo
      echo "**Where it stopped:** the loop is not converging. The automation stops"
      echo "it here rather than spending a fourth cycle."
      echo
      echo "**Options**"
      echo
      echo "- **A — re-refine the work item.** Read the three rejection comments"
      echo "  together and look for the criterion that keeps failing. Usually the"
      echo "  criteria are ambiguous or contradictory. Cheapest real fix."
      echo "- **B — split the item.** If rejections hit different criteria each"
      echo "  time, the story is too big. Split it and dispatch the pieces."
      echo "- **C — dispatch on a different harness.** Right when the rejections"
      echo "  all hit the same criterion in the same way: a correlated blind spot"
      echo "  that a different model may not share. Not available in"
      echo "  single-harness mode (PRD §11.2)."
      echo
      echo "**Recommendation:** A, unless the three rejections name three"
      echo "different criteria — then B."
      echo
      [ -n "$RUN_URL" ] && echo "Run: ${RUN_URL}"
      echo
      echo "Threshold: \`role-packs/qa/policy.yaml\` (\`verdict.rejection_escalation_threshold\`)."
    } > "$report"

    gh issue comment "$ISSUE" --body-file "$report"
    gh issue edit "$ISSUE" --add-label "needs-human"
    cat "$report" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
    echo "Issue #${ISSUE} escalated: needs-human applied after ${rejections} rejections."
    ;;

  *)
    echo "qa-verdict: unknown MODE '${MODE}' (expected close-guard or ladder)" >&2
    exit 2
    ;;
esac
