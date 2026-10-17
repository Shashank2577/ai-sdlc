#!/usr/bin/env bash
# A role's skills, forbidden actions and HITL triggers must reach the
# session (#320). compile-pack.py rendered all of them into a
# system-prompt.md that nothing read, so every skill was inert.
#
# Extracts the real "Install the role's skills" and "Assemble the session
# prompt" steps from dispatch.yml, compiles every committed role pack with
# the real compiler, and runs both steps against it: each role's skills
# must be installed as SKILL.md files where Claude Code loads them, listed
# by description in the prompt and not pasted into it, and the prompt must
# carry the pack's forbidden list and HITL triggers.
#
#   bash scripts/test-dispatch-skills.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bin" "$WORK/tmp"

FAIL=0
ok() { if [ "$2" = 0 ]; then echo "  ok    $1"; else echo "  FAIL  $1"; FAIL=1; fi; }

echo "dispatch.yml wiring"
python3 - "$REPO_ROOT/.github/workflows/dispatch.yml" "$WORK" <<'PY'
import sys, yaml
wf = yaml.safe_load(open(sys.argv[1]))
steps = wf["jobs"]["session"]["steps"]
names = [s.get("name") for s in steps]
by = {s.get("name"): s for s in steps}
fail = 0
def ok(msg, cond):
    global fail
    print(("  ok    " if cond else "  FAIL  ") + msg)
    fail |= not cond
install, prompt, agent = (by.get(n) for n in (
    "Install the role's skills for the session",
    "Assemble the session prompt",
    "Run agent session (claude-code)"))
ok("has an install-skills step", install is not None)
ok("has a prompt step", prompt is not None)
ok("has a claude-code agent step", agent is not None)
if not (install and prompt and agent):
    sys.exit(1)
ok("skills are installed before the claude-code session starts",
   names.index(install["name"]) < names.index(agent["name"]))
ok("install runs for the claude-code harness", install.get("if") == "inputs.harness == 'claude-code'")
ok("install reads the compiled pack", install["env"].get("PACK_DIR") == "${{ steps.pack.outputs.pack_dir }}")
ok("prompt step reads the compiled pack", prompt["env"].get("PACK_DIR") == "${{ steps.pack.outputs.pack_dir }}")
# Skills load from the `user` setting source. An agent step that narrows
# the sources without it, or denies the Skill tool, silently drops them.
args = agent["with"].get("claude_args", "")
ok("agent step keeps the user setting source",
   "setting-sources" not in args or "user" in args.split("setting-sources", 1)[1].split("\n")[0])
ok("agent step does not deny the Skill tool", "Skill" not in args)
open(f"{sys.argv[2]}/install.sh", "w").write(install["run"])
open(f"{sys.argv[2]}/prompt.sh", "w").write(prompt["run"])
sys.exit(fail)
PY
[ $? = 0 ] || FAIL=1
[ -f "$WORK/install.sh" ] && [ -f "$WORK/prompt.sh" ] || { echo "FAILED"; exit 1; }

# `gh pr list` finds no PRs; nothing else reaches the network from these steps.
cat > "$WORK/bin/gh" <<'STUB'
#!/usr/bin/env bash
[ "$1" = "pr" ] && [ "$2" = "list" ] && { echo '[]'; exit 0; }
echo "unexpected gh call: $*" >&2; exit 1
STUB
chmod +x "$WORK/bin/gh"
printf '{"number":7,"state":"OPEN","title":"T","body":"Build the thing.","updatedAt":"x","labels":[]}' \
  > "$WORK/tmp/issue.json"

export PATH="$WORK/bin:$PATH" RUNNER_TEMP="$WORK/tmp" GITHUB_REPOSITORY=o/r \
  GITHUB_STEP_SUMMARY="$WORK/summary" GITHUB_OUTPUT="$WORK/out" ISSUE=7 \
  PRODUCT_REPO=o/p TURNS=1 COST_USD=1 TOKENS=1 WALL_CLOCK=1 BUDGET_SOURCE=t \
  RUN_URL=u REQUIRES_PR=true MATCHED_LABEL=status:ready
P="$WORK/tmp/session-prompt.md"

roles=$(cd "$REPO_ROOT/role-packs" && for d in */; do [ -f "$d/pack.yaml" ] && echo "${d%/}"; done)
[ -n "$roles" ]; ok "found committed role packs" $?

for role in $roles; do
  echo "$role"
  home="$WORK/home-$role"
  mkdir -p "$home"
  python3 "$REPO_ROOT/compiler/compile-pack.py" --role "$role" --harness claude-code \
    --out "$WORK/pack" >/dev/null 2>"$WORK/err"; ok "pack compiles" $?
  pack_dir="$WORK/pack/$role/claude-code"
  (cd "$WORK" && HOME="$home" PACK_DIR="$pack_dir" bash "$WORK/install.sh") >/dev/null 2>"$WORK/err"
  ok "skills install" $?
  (cd "$WORK" && ROLE="$role" CP_DIR="$REPO_ROOT" PACK_DIR="$pack_dir" bash "$WORK/prompt.sh") \
    >/dev/null 2>"$WORK/err"; ok "prompt builds" $?
  python3 - "$REPO_ROOT/role-packs/$role" "$home/.claude/skills" "$P" <<'PY'
import re, sys, yaml
from pathlib import Path
src, installed, prompt = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]).read_text()
fail = 0
def ok(msg, cond):
    global fail
    print(("  ok    " if cond else "  FAIL  ") + msg)
    fail |= not cond
def front(text):
    m = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    return (yaml.safe_load(m.group(1)), text[m.end():]) if m else ({}, text)
sources = sorted((src / "skills").glob("*.md"))
ok(f"pack has skills ({len(sources)})", bool(sources))
ok("installs exactly the pack's skills",
   sorted(p.name for p in installed.iterdir()) == sorted(p.stem for p in sources))
for s in sources:
    meta, body = front(s.read_text())
    want = " ".join(meta["description"].split())
    skill_md = installed / s.stem / "SKILL.md"
    got, got_body = front(skill_md.read_text()) if skill_md.is_file() else ({}, "")
    ok(f"{s.stem}: SKILL.md names the skill", got.get("name") == s.stem)
    ok(f"{s.stem}: SKILL.md carries the description", got.get("description") == want)
    ok(f"{s.stem}: SKILL.md carries the body", got_body.strip() == body.strip())
    ok(f"{s.stem}: prompt lists it by description", f"- `{s.stem}`: {want}" in prompt)
    heading = next(l for l in body.splitlines() if l.startswith("# "))
    ok(f"{s.stem}: prompt does not paste the body", heading not in prompt)
policy = yaml.safe_load((src / "policy.yaml").read_text())
ok("prompt has a forbidden-actions section", "## Forbidden actions" in prompt)
ok("prompt lists every forbidden action", all(f"- `{a}`" in prompt for a in policy["forbidden"]))
ok("prompt has an escalate-when section", "## Escalate to a human when" in prompt)
ok("prompt lists every HITL trigger", all(f"- `{t}`" in prompt for t in policy["hitl_triggers"]))
ok("prompt names the escalation label", f"add the `{policy['escalation']['label']}` label" in prompt)
sys.exit(fail)
PY
  [ $? = 0 ] || FAIL=1
done

# Fake control plane for the failure cases.
mkdir -p "$WORK/cp/role-packs/r" "$WORK/fakepack/skills/x"
echo "charter" > "$WORK/cp/role-packs/r/charter.md"
echo "conventions" > "$WORK/cp/CONVENTIONS.md"
run_prompt() { (cd "$WORK" && ROLE=r CP_DIR="$WORK/cp" PACK_DIR="${1:-}" bash "$WORK/prompt.sh") >/dev/null 2>&1; }
has() { grep -qF -- "$1" "$P"; }

echo "malformed forbidden list"
printf 'forbidden: push_to_main\nhitl_triggers: [budget_breach]\n' > "$WORK/cp/role-packs/r/policy.yaml"
run_prompt; [ $? -ne 0 ]; ok "step fails rather than omit it" $?

echo "malformed HITL triggers"
printf 'forbidden: [push_to_main]\nhitl_triggers: [{a: b}]\n' > "$WORK/cp/role-packs/r/policy.yaml"
run_prompt; [ $? -ne 0 ]; ok "step fails rather than omit them" $?

echo "a harness with no compiled skills (codex)"
printf 'forbidden: [push_to_main]\nhitl_triggers: [budget_breach]\n' > "$WORK/cp/role-packs/r/policy.yaml"
run_prompt "$WORK/nopack"; ok "prompt builds" $?
! has "## Your role's skills"; ok "lists no skills" $?
has '- `push_to_main`'; ok "still carries the forbidden list" $?
has "add the \`needs-human\` label"; ok "defaults the escalation label" $?

echo "a compiled skill with no SKILL.md"
(cd "$WORK" && HOME="$WORK/home-broken" PACK_DIR="$WORK/fakepack" bash "$WORK/install.sh") >/dev/null 2>&1
[ $? -ne 0 ]; ok "install fails rather than ship it half-installed" $?

[ "$FAIL" = 0 ] && echo "all passed" || { echo "FAILED"; exit 1; }
