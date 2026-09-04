#!/usr/bin/env bash
# A `git push` refused with "refusing to allow a Personal Access Token to
# create or update workflow ... without `workflow` scope" is, for every
# role but devops, the credential boundary working as designed:
# FOUNDRY_DEV_TOKEN deliberately lacks `workflow` scope (ADR-0001), so no
# non-devops role can push a change under `.github/workflows/`.
#
# The message alone does not say whether *this* branch is the cause. A
# #134 session spent roughly a third of its turns on a credential theory
# before finding the real, mundane reason: it had genuinely added a
# workflow file. This computes the answer instead of guessing at it —
# what the branch actually changes under `.github/workflows/`, relative
# to its merge base with the target branch — so a session (or a human
# reading the escalation) gets a true statement instead of a theory.
#
# This cannot reproduce GitHub's server-side scope check itself — that
# requires a real token and a real push — so it only ever answers "does
# this branch's diff explain the rejection", never "will the push be
# rejected". Say so, plainly, when the diff is empty: the cause is
# unknown, not cleared.
#
#   scripts/diagnose-workflow-push-refusal.sh [<base-ref>]
#
# <base-ref> defaults to origin/main. Prints a human-readable diagnosis to
# stdout and exits 0 always — this is a diagnostic, not a gate.
set -euo pipefail

BASE_REF="${1:-origin/main}"

if ! MERGE_BASE="$(git merge-base HEAD "$BASE_REF" 2>&1)"; then
  echo "Could not compute a merge base between HEAD and ${BASE_REF}:"
  echo "$MERGE_BASE"
  echo
  echo "Cause unknown — do not assume a credential or repo-wide fault."
  exit 0
fi

CHANGED="$(git diff --name-only "$MERGE_BASE" HEAD -- .github/workflows/)"

echo "Merge base with ${BASE_REF}: ${MERGE_BASE}"
echo
echo '$ git diff --name-only '"${MERGE_BASE}"' HEAD -- .github/workflows/'
if [ -n "$CHANGED" ]; then
  echo "$CHANGED"
  echo
  echo "This branch changes the file(s) above under .github/workflows/."
  echo "That is why the push was refused: this role's credential does not"
  echo "carry \`workflow\` scope, by design (see"
  echo "role-packs/devops/skills/least-privilege-credentials.md). This is"
  echo "not a broken or misconfigured credential — do not investigate the"
  echo "token further."
  echo
  echo "Remove the change(s) above from this branch and hand the workflow"
  echo "edit to devops instead of pushing it yourself (the pattern tracked"
  echo "in #128: escalate with the exact patch, a devops credential"
  echo "applies it)."
else
  echo "(empty)"
  echo
  echo "This branch changes no file under .github/workflows/ relative to"
  echo "its merge base with ${BASE_REF}. The rejection names a workflow"
  echo "file, but this diff does not contain one — the cause is not"
  echo "established by this branch's contents."
  echo
  echo "Do not assert a cause you have not verified (a stale base, a wrong"
  echo "branch, a re-push of an old ref are guesses, not findings)."
  echo "Escalate with this exact output as evidence instead of a theory."
fi
