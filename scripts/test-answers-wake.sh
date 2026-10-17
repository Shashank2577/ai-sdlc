#!/usr/bin/env bash
# answers.yml wakes the role that asked a question (#321), on an answer or
# on expiry. Extracts the "Wake answered items, expire stale ones" `run:`
# block and runs it verbatim against a stub `gh`, with the real
# scripts/questions.jq and policies/gates.yaml. The cases that matter most
# are the ones that must NOT wake: agents comment with the owner's PAT, so
# an author check alone would let an agent answer its own question.
#
#   bash scripts/test-answers-wake.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bin" "$WORK/tmp" "$WORK/cp/scripts" "$WORK/cp/policies" \
  "$WORK/cp/role-packs/product-manager"
ln -s "$REPO_ROOT/scripts/questions.jq" "$WORK/cp/scripts/questions.jq"
ln -s "$REPO_ROOT/policies/gates.yaml" "$WORK/cp/policies/gates.yaml"
echo "role: product-manager" > "$WORK/cp/role-packs/product-manager/pack.yaml"

python3 - "$REPO_ROOT/.github/workflows/answers.yml" "$WORK/wake.sh" <<'PY' || exit 1
import sys, yaml
wf = yaml.safe_load(open(sys.argv[1]))
for job in wf["jobs"].values():
    for step in job.get("steps", []):
        if step.get("name") == "Wake answered items, expire stale ones":
            open(sys.argv[2], "w").write(step["run"])
            sys.exit(0)
sys.exit("wake step not found")
PY

# Every call is logged. `issue view` prints $META, `api` prints $COMMENTS,
# `issue list` prints $LIST; `workflow run` fails when RUN_FAIL=1 and logs
# which token started it.
cat > "$WORK/bin/gh" <<'STUB'
#!/usr/bin/env bash
echo "gh $*" >> "$CALLS"
case "$1 $2" in
  "issue view") cat "$META" ;;
  "issue list") printf '%s\n' $LIST ;;
  "workflow run")
    echo "token=$GH_TOKEN" >> "$CALLS"
    [ "${RUN_FAIL:-0}" = 1 ] && { echo "HTTP 403" >&2; exit 1; }
    ;;
  "issue comment")
    for ((i=1; i<=$#; i++)); do
      if [ "${!i}" = "--body-file" ]; then j=$((i+1)); cat "${!j}" >> "$WORK/comments.md"; fi
    done
    ;;
  api*) cat "$COMMENTS" ;;
esac
exit 0
STUB
chmod +x "$WORK/bin/gh"

export PATH="$WORK/bin:$PATH" WORK RUNNER_TEMP="$WORK/tmp" GITHUB_REPOSITORY=o/r \
  GITHUB_STEP_SUMMARY="$WORK/summary" GH_TOKEN=bot-token DISPATCH_TOKEN=dispatch-token \
  RUN_URL=https://run/1 CALLS="$WORK/calls.log" META="$WORK/meta.json" \
  COMMENTS="$WORK/comments.json"

# 2026-10-17T10:00:00Z as an epoch, so SLA arithmetic is deterministic.
T0=$(python3 -c 'import datetime as d; print(int(d.datetime(2026,10,17,10,tzinfo=d.timezone.utc).timestamp()))')

FAIL=0
ok() { if [ "$2" = 0 ]; then echo "  ok    $1"; else echo "  FAIL  $1"; FAIL=1; fi; }
called() { grep -qF -- "$1" "$CALLS"; }

# meta <labels...> — the item's state and labels.
meta() {
  python3 -c 'import json,sys; print(json.dumps({"state":"OPEN","labels":[{"name":n} for n in sys.argv[1:]]}))' "$@" > "$META"
}
# c <login> <type> <association> <minute> <body> — one comment at 10:<minute>Z.
c() {
  python3 -c 'import json,sys
l,t,a,m,b=sys.argv[1:]
print(json.dumps({"user":{"login":l,"type":t},"author_association":a,
  "created_at":f"2026-10-17T10:{int(m):02d}:00Z","html_url":f"https://c/{m}","body":b}))' "$@"
}
Q='<!-- foundry:questions role=product-manager product=foundry-program -->
### Questions before I continue
**Q1. Who is the user?**'
END='<!-- foundry:dispatch result=success outcome=awaiting-answer breach=0 -->'
comments() { printf '%s\n' "$@" | jq -s . > "$COMMENTS"; }
asked() {  # the question at 10:00 and its session end at 10:02, plus "$@"
  comments "$(c owner User OWNER 0 "$Q")" "$(c github-actions[bot] Bot NONE 2 "$END")" "$@"
}
run() {  # run [issue] — EVENT_ISSUE, or the sweep when empty
  : > "$CALLS"; : > "$WORK/comments.md"
  EVENT_ISSUE="${1-}" NOW_EPOCH="${NOW:-$((T0 + 600))}" bash "$WORK/wake.sh" > "$WORK/out" 2>&1
}
cd "$WORK/cp" || exit 1

echo "an answer from a person with write access, after the session ended"
meta status:ready awaiting:answer
asked "$(c owner User OWNER 5 'Q1: B')"
run 7; ok "step succeeds" $?
called "gh issue edit 7 --repo o/r --remove-label awaiting:answer"; ok "removes awaiting:answer" $?
called "gh workflow run dispatch.yml --repo o/r -f issue=7 -f role=product-manager -f product=foundry-program"
ok "re-dispatches the role and product the question recorded" $?
called "token=dispatch-token"; ok "starts dispatch with the dispatch token" $?
grep -qF '<!-- foundry:answer-wake reason=answered -->' "$WORK/comments.md"; ok "records the wake with a marker" $?
grep -qF '| Answered by | @owner |' "$WORK/comments.md"; ok "names who answered" $?

echo "a collaborator's answer counts too"
asked "$(c teammate User COLLABORATOR 5 'Q1: A')"
run 7; called "gh workflow run"; ok "wakes" $?

no_wake() {  # no_wake <description>
  run 7; local rc=$?
  ! called "gh workflow run" && ! called "--remove-label awaiting:answer"; ok "$1" $?
  [ "$rc" = 0 ]; ok "  ... and the step still succeeds" $?
}
echo "replies that must not wake"
asked; no_wake "no reply yet, inside the SLA"
comments "$(c owner User OWNER 0 "$Q")" "$(c owner User OWNER 1 'Q1: B  (agent, mid-session)')" \
  "$(c github-actions[bot] Bot NONE 2 "$END")"
no_wake "an OWNER comment posted before the session ended (the agent's own PAT)"
asked "$(c rando User NONE 5 'Q1: B')"; no_wake "a reply from someone without write access"
asked "$(c codex[bot] Bot NONE 5 'Q1: B')"; no_wake "a bot's reply"
asked "$(c owner User OWNER 5 '<!-- foundry:dispatch result=success --> Q1: B')"
no_wake "a comment carrying a foundry marker"
comments "$(c owner User OWNER 0 "$Q")" "$(c owner User OWNER 5 'Q1: B')"
no_wake "the session that asked never reported its end (a reply can't be told from the agent)"
meta status:in-progress awaiting:answer; asked "$(c owner User OWNER 5 'Q1: B')"
no_wake "a session is running on the item"
meta status:ready; asked "$(c owner User OWNER 5 'Q1: B')"
no_wake "the item is not awaiting an answer"
meta status:ready awaiting:answer

echo "expiry"
asked
NOW=$((T0 + 71 * 3600)) no_wake "71h after the session ended, under the 72h SLA"
NOW=$((T0 + 73 * 3600)) run 7; ok "step succeeds" $?
called "gh workflow run dispatch.yml --repo o/r -f issue=7 -f role=product-manager -f product=foundry-program"
ok "wakes the role once the SLA has passed" $?
called "--remove-label awaiting:answer"; ok "removes awaiting:answer" $?
grep -qF 'reason=expired' "$WORK/comments.md"; ok "records it as expired" $?
grep -qF 'on the recommended answers' "$WORK/comments.md"; ok "says it proceeds on the recommendations" $?

echo "the asking session died before reporting its end"
comments "$(c owner User OWNER 0 "$Q")"
NOW=$((T0 + 71 * 3600)) no_wake "within the SLA of the question itself"
NOW=$((T0 + 73 * 3600)) run 7; called "-f issue=7 -f role=product-manager" && grep -qF 'reason=expired' "$WORK/comments.md"
ok "expires from the question's own time instead of waiting forever" $?

echo "a question nothing can wake"
comments "$(c rando User NONE 0 "$Q")" "$(c github-actions[bot] Bot NONE 2 "$END")" \
  "$(c owner User OWNER 5 'Q1: B')"
run 7; ok "step succeeds" $?
called "--remove-label awaiting:answer --add-label needs-human"; ok "a forged question from outside: hands it to a person" $?
! called "gh workflow run"; ok "  ... and dispatches nothing" $?
comments "$(c owner User OWNER 0 "${Q/product-manager/ghost}")" "$(c github-actions[bot] Bot NONE 2 "$END")" \
  "$(c owner User OWNER 5 'Q1: B')"
run 7; called "--add-label needs-human" && ! called "gh workflow run"; ok "a role with no pack: needs-human, no dispatch" $?

echo "the dispatch fails"
asked "$(c owner User OWNER 5 'Q1: B')"
RUN_FAIL=1 run 7; [ $? != 0 ]; ok "step fails" $?
called "gh issue edit 7 --repo o/r --add-label awaiting:answer"; ok "restores awaiting:answer so the sweep retries" $?
[ ! -s "$WORK/comments.md" ]; ok "claims no wake on the item" $?

echo "the sweep checks every waiting item"
LIST="7 8" run ""; ok "step succeeds" $?
called "gh issue list --repo o/r --state open --label awaiting:answer"; ok "lists the waiting items" $?
called "-f issue=7" && called "-f issue=8"; ok "wakes each answered item" $?

[ "$FAIL" = 0 ] && echo "all passed" || { echo "FAILED"; exit 1; }
