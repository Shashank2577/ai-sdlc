#!/usr/bin/env bash
# Security verdict enforcement — issue side. Three modes, driven by the
# event that fired the workflow. Mirrors scripts/qa-verdict.sh exactly,
# s/qa/security/.
#
#   close-guard      a rejected work item that gets closed is reopened
#   ladder           the third security:rejected on one item escalates to
#                     a human
#   return-to-ready  security:rejected on an in-review story hands it back
#                     to status:ready, so the author's role is dispatchable
#                     again (mirrors #82) — security:rejected itself is
#                     never removed, it stays as the merge veto
#
# Rejection counts come from the tracker's own `labeled` timeline events,
# never from anything an agent reports. Event-derived, per REQ-006.
#
# return-to-ready reads labels from the event payload (LABELS_JSON), the
# scripts/terminal-label.sh model, so a story already at status:ready makes
# zero `gh` calls — this fires on every label change, not only rejections.
set -euo pipefail

: "${MODE:?}" "${ISSUE:?}" "${GITHUB_REPOSITORY:?}"
RUN_URL="${RUN_URL:-}"
TMP="${RUNNER_TEMP:-/tmp}"

# The policy file is the source of truth for the threshold, not the
# workflow. CONVENTIONS.md: if the policy and the script disagree, the
# policy wins — so read it rather than restating it.
POLICY="${SECURITY_POLICY:-role-packs/security/policy.yaml}"
if [ -z "${THRESHOLD:-}" ] && [ -f "$POLICY" ]; then
  THRESHOLD=$(awk '/^[[:space:]]*rejection_escalation_threshold:[[:space:]]*[0-9]+/ {print $2; exit}' "$POLICY")
fi
THRESHOLD="${THRESHOLD:-3}"

has_label() {
  gh issue view "$ISSUE" --json labels --jq \
    "[.labels[].name] | index(\"$1\") != null" 2>/dev/null | grep -q true
}

# Every time security:rejected was applied, from the issue's event history.
count_rejections() {
  gh api --paginate "repos/${GITHUB_REPOSITORY}/issues/${ISSUE}/events" \
    --jq '.[] | select(.event == "labeled" and .label.name == "security:rejected") | .created_at' \
    2>/dev/null | grep -c . || true
}

case "$MODE" in

  close-guard)
    if ! has_label "security:rejected"; then
      echo "Issue #${ISSUE} closed without a security:rejected verdict. Nothing to do."
      exit 0
    fi

    report="${TMP}/close-guard.md"
    {
      echo "### Reopened — security verdict is binding"
      echo
      echo "This work item carries \`security:rejected\`, so it cannot be"
      echo "closed. A rejected story that quietly closes is the one failure"
      echo "the security veto exists to prevent, so the automation reopens"
      echo "it rather than trusting the close."
      echo
      echo "To close it, one of:"
      echo
      echo "1. Fix what security found and have security re-review — the"
      echo "   verdict flips to \`security:approved\` and closure is unblocked."
      echo "2. Remove the \`security:rejected\` label first. That takes write"
      echo "   access, so overruling security is a human decision recorded in"
      echo "   the event log."
      echo
      [ -n "$RUN_URL" ] && echo "Run: ${RUN_URL}"
      echo
      echo "Policy of record: \`role-packs/security/policy.yaml\` (\`verdict.intended_to_block_closure\`)."
    } > "$report"

    gh issue reopen "$ISSUE" --comment "$(cat "$report")"
    cat "$report" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
    echo "Issue #${ISSUE} reopened: security:rejected blocks closure."
    ;;

  ladder)
    rejections=$(count_rejections)
    echo "Issue #${ISSUE}: ${rejections} security:rejected event(s), threshold ${THRESHOLD}."

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
      echo "### Escalation — ${rejections} security rejections on one work item"
      echo
      echo "Security has rejected this item ${rejections} times. Past the"
      echo "threshold of ${THRESHOLD}, the assumption changes: three"
      echo "rejections is rarely three unrelated mistakes, it is usually a"
      echo "work item that was wrong from the start and that everyone has"
      echo "been patching around."
      echo
      echo "**Goal:** deliver #${ISSUE} to its stated acceptance criteria"
      echo "without the exposure security keeps finding."
      echo
      echo "**What ran:** ${rejections} developer→security cycles. Each"
      echo "rejection comment is above, with the finding that produced it."
      echo
      echo "**Where it stopped:** the loop is not converging. The automation"
      echo "stops it here rather than spending a fourth cycle."
      echo
      echo "**Options**"
      echo
      echo "- **A — re-refine the work item.** Read the three rejection"
      echo "  comments together and look for the exposure that keeps"
      echo "  recurring. Usually the approach itself, not the acceptance"
      echo "  criteria, is the problem. Cheapest real fix."
      echo "- **B — split the item.** If rejections hit different findings"
      echo "  each time, the story is too big. Split it and dispatch the"
      echo "  pieces."
      echo "- **C — dispatch on a different harness.** Right when the"
      echo "  rejections all hit the same finding in the same way: a"
      echo "  correlated blind spot a different model may not share. Not"
      echo "  available in single-harness mode (PRD §11.2)."
      echo
      echo "**Recommendation:** A, unless the three rejections name three"
      echo "different findings — then B."
      echo
      [ -n "$RUN_URL" ] && echo "Run: ${RUN_URL}"
      echo
      echo "Threshold: \`role-packs/security/policy.yaml\` (\`verdict.rejection_escalation_threshold\`)."
    } > "$report"

    gh issue comment "$ISSUE" --body-file "$report"
    gh issue edit "$ISSUE" --add-label "needs-human"
    cat "$report" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
    echo "Issue #${ISSUE} escalated: needs-human applied after ${rejections} rejections."
    ;;

  return-to-ready)
    LABELS_JSON="${LABELS_JSON:-[]}"
    if ! jq -e '[.[].name] | index("status:in-review")' <<<"$LABELS_JSON" >/dev/null; then
      echo "Issue #${ISSUE}: not at status:in-review. Nothing to do."
      exit 0
    fi

    gh issue edit "$ISSUE" --remove-label "status:in-review" --add-label "status:ready"
    echo "Issue #${ISSUE}: security:rejected returned it to status:ready — the author's role is dispatchable again."
    ;;

  *)
    echo "security-verdict: unknown MODE '${MODE}' (expected close-guard, ladder, or return-to-ready)" >&2
    exit 2
    ;;
esac
