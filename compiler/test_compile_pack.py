#!/usr/bin/env python3
"""Tests for the role-pack compiler. Stdlib only — runs anywhere python3 does.

    python3 compiler/test_compile_pack.py
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent

spec = importlib.util.spec_from_file_location("compile_pack", HERE / "compile-pack.py")
cp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp)


MINIMAL_PACK = {
    "pack.yaml": """
version: 0
role: widget
harness_compat:
  claude-code:
    supported: true
identity:
  git_user: widget-bot
  token_secret: WIDGET_TOKEN
  provisioned: false
""",
    "charter.md": "# Widget — charter\n\nDo widget things.\n",
    "tools.yaml": """
version: 0
role: widget
shell:
  allow:
    - "git status"
    - "git log*"
  deny:
    - "git push*--force*"
""",
    "policy.yaml": """
version: 0
role: widget
budgets:
  turns: 10
  cost_usd: 1.5
  tokens: 1000
  wall_clock_minutes: 5
  max_retries: 1
forbidden:
  - push_to_default_branch
hitl_triggers:
  - budget_breach
escalation:
  label: needs-human
""",
}


class PackFixture:
    """A throwaway role-packs/ tree with the compiler pointed at it."""

    def __init__(self, files: dict[str, str], role: str = "widget"):
        self.tmp = Path(tempfile.mkdtemp())
        self.role = role
        root = self.tmp / "role-packs" / role
        root.mkdir(parents=True)
        for name, body in files.items():
            (root / name).write_text(body)
        self._saved = (cp.REPO_ROOT, cp.PACKS_DIR)
        cp.REPO_ROOT = self.tmp
        cp.PACKS_DIR = self.tmp / "role-packs"

    def add_skill(self, name: str, body: str,
                  frontmatter: str | None = "description: Use when doing widget things.\n") -> None:
        d = cp.PACKS_DIR / self.role / "skills"
        d.mkdir(exist_ok=True)
        head = "" if frontmatter is None else f"---\n{frontmatter}---\n\n"
        (d / f"{name}.md").write_text(head + body)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        cp.REPO_ROOT, cp.PACKS_DIR = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestValidation(unittest.TestCase):
    def test_valid_pack_loads(self):
        with PackFixture(MINIMAL_PACK):
            pack = cp.read_pack("widget")
            self.assertEqual(pack["role"], "widget")
            self.assertEqual(pack["policy"]["budgets"]["turns"], 10)

    def test_missing_role_directory(self):
        with PackFixture(MINIMAL_PACK):
            with self.assertRaises(cp.PackError) as ctx:
                cp.read_pack("nope")
            self.assertIn("no role pack at role-packs/nope/", str(ctx.exception))

    def test_missing_required_file_is_named(self):
        files = dict(MINIMAL_PACK)
        del files["tools.yaml"]
        with PackFixture(files):
            with self.assertRaises(cp.PackError) as ctx:
                cp.read_pack("widget")
            self.assertIn("tools.yaml", str(ctx.exception))

    def test_a_pack_without_a_credential_is_rejected(self):
        # Widening one shared token to unblock a role raises every role's
        # reach. Each pack has to name what it needs.
        files = dict(MINIMAL_PACK)
        files["pack.yaml"] = files["pack.yaml"].replace(
            "  token_secret: WIDGET_TOKEN\n", "")
        with PackFixture(files):
            with self.assertRaises(cp.PackError) as ctx:
                cp.read_pack("widget")
            self.assertIn("token_secret", str(ctx.exception))
            self.assertIn("not dispatchable", str(ctx.exception))

    def test_the_credential_is_compiled_for_the_dispatcher(self):
        with PackFixture(MINIMAL_PACK):
            out = cp.compile_claude_code(cp.read_pack("widget"))
        self.assertEqual(out["token-secret"].strip(), "WIDGET_TOKEN")

    def test_app_permissions_are_compiled_for_every_harness(self):
        # ADR-0011: the dispatcher mints the App token from this file.
        files = dict(MINIMAL_PACK)
        files["pack.yaml"] = files["pack.yaml"].replace(
            "  token_secret: WIDGET_TOKEN\n",
            "  token_secret: WIDGET_TOKEN\n  github_permissions:\n"
            "    contents: write\n    issues: write\n")
        with PackFixture(files):
            pack = cp.read_pack("widget")
            for compile_fn in (cp.compile_claude_code, cp.compile_codex, cp.compile_opencode):
                self.assertEqual(compile_fn(pack)["github-permissions"],
                                 "contents=write\nissues=write\n")

    def test_no_app_permissions_compiles_to_an_empty_file(self):
        # Empty, not omitted: the dispatcher refuses to mint from it rather
        # than inherit the installation's whole permission set.
        with PackFixture(MINIMAL_PACK):
            out = cp.compile_claude_code(cp.read_pack("widget"))
        self.assertEqual(out["github-permissions"], "")

    def test_an_unknown_app_permission_is_rejected(self):
        files = dict(MINIMAL_PACK)
        files["pack.yaml"] = files["pack.yaml"].replace(
            "  token_secret: WIDGET_TOKEN\n",
            "  token_secret: WIDGET_TOKEN\n  github_permissions:\n    administration: write\n")
        with PackFixture(files):
            with self.assertRaises(cp.PackError) as ctx:
                cp.read_pack("widget")
            self.assertIn("administration", str(ctx.exception))

    def test_real_packs_keep_workflows_write_to_devops(self):
        for root in sorted(cp.PACKS_DIR.glob("*/pack.yaml")):
            pack = cp.read_pack(root.parent.name)
            has = pack["github_permissions"].get("workflows") == "write"
            self.assertEqual(has, pack["role"] == "devops", pack["role"])

    def test_dispatchable_from_defaults_to_status_ready(self):
        # #67: a pack silent on this inherits today's global behaviour
        # rather than becoming un-dispatchable or wide open.
        with PackFixture(MINIMAL_PACK):
            pack = cp.read_pack("widget")
            out = cp.compile_claude_code(pack)
        self.assertEqual(pack["dispatchable_from"], ["status:ready"])
        self.assertEqual(out["dispatchable-from"].strip(), "status:ready")

    def test_dispatchable_from_is_declared_by_the_pack(self):
        files = dict(MINIMAL_PACK)
        files["pack.yaml"] += "dispatchable_from:\n  - status:in-review\n"
        with PackFixture(files):
            pack = cp.read_pack("widget")
            out = cp.compile_claude_code(pack)
        self.assertEqual(pack["dispatchable_from"], ["status:in-review"])
        self.assertEqual(out["dispatchable-from"].strip(), "status:in-review")

    def test_dispatchable_from_must_be_a_non_empty_list(self):
        files = dict(MINIMAL_PACK)
        files["pack.yaml"] += "dispatchable_from: []\n"
        with PackFixture(files):
            with self.assertRaises(cp.PackError) as ctx:
                cp.read_pack("widget")
            self.assertIn("dispatchable_from", str(ctx.exception))

    def test_dispatchable_from_rejects_non_string_entries(self):
        files = dict(MINIMAL_PACK)
        files["pack.yaml"] += "dispatchable_from:\n  - 1\n"
        with PackFixture(files):
            with self.assertRaises(cp.PackError) as ctx:
                cp.read_pack("widget")
            self.assertIn("dispatchable_from", str(ctx.exception))

    def test_produces_defaults_to_pull_request_required(self):
        # #99: a pack silent on this inherits today's global behaviour —
        # a clean session is expected to open a pull request — rather than
        # silently exempting an undeclared role from the check.
        with PackFixture(MINIMAL_PACK):
            pack = cp.read_pack("widget")
            out = cp.compile_claude_code(pack)
        self.assertEqual(pack["produces"], cp.DEFAULT_PRODUCES)
        self.assertIn("pull_request", out["produces"].splitlines())

    def test_produces_is_declared_by_the_pack(self):
        files = dict(MINIMAL_PACK)
        files["pack.yaml"] += "produces:\n  - comments\n  - status\n"
        with PackFixture(files):
            pack = cp.read_pack("widget")
            out = cp.compile_claude_code(pack)
        self.assertEqual(pack["produces"], ["comments", "status"])
        self.assertNotIn("pull_request", out["produces"].splitlines())

    def test_produces_must_be_a_non_empty_list(self):
        files = dict(MINIMAL_PACK)
        files["pack.yaml"] += "produces: []\n"
        with PackFixture(files):
            with self.assertRaises(cp.PackError) as ctx:
                cp.read_pack("widget")
            self.assertIn("produces", str(ctx.exception))

    def test_produces_rejects_non_string_entries(self):
        files = dict(MINIMAL_PACK)
        files["pack.yaml"] += "produces:\n  - 1\n"
        with PackFixture(files):
            with self.assertRaises(cp.PackError) as ctx:
                cp.read_pack("widget")
            self.assertIn("produces", str(ctx.exception))

    def test_no_code_writing_role_may_edit_the_pipeline(self):
        # PRD §3 gives .github/workflows/ to DevOps. A role that writes code
        # must not be able to edit the check that reviews it.
        import yaml
        for role in ("developer", "qa", "product-manager"):
            path = HERE.parent / "role-packs" / role / "policy.yaml"
            if not path.is_file():
                continue
            with self.subTest(role=role):
                scope = (yaml.safe_load(path.read_text()) or {}).get("write_scope", {})
                allow = scope.get("allow") or []
                self.assertFalse([a for a in allow if a.startswith(".github")],
                                 f"{role} must not have .github/** in write_scope")

    def test_role_must_match_directory(self):
        files = dict(MINIMAL_PACK)
        files["pack.yaml"] = files["pack.yaml"].replace("role: widget", "role: gadget")
        with PackFixture(files):
            with self.assertRaises(cp.PackError) as ctx:
                cp.read_pack("widget")
            self.assertIn("directory says", str(ctx.exception))

    def test_unbudgeted_role_is_rejected(self):
        files = dict(MINIMAL_PACK)
        files["policy.yaml"] = files["policy.yaml"].replace("  tokens: 1000\n", "")
        with PackFixture(files):
            with self.assertRaises(cp.PackError) as ctx:
                cp.read_pack("widget")
            self.assertIn("tokens", str(ctx.exception))
            self.assertIn("unbudgeted role cannot be dispatched", str(ctx.exception))

    def test_a_pack_without_a_cost_ceiling_is_rejected(self):
        # Cost is the enforced budget line; a pack without one cannot be
        # dispatched safely.
        files = dict(MINIMAL_PACK)
        files["policy.yaml"] = files["policy.yaml"].replace("  cost_usd: 1.5\n", "")
        with PackFixture(files):
            with self.assertRaises(cp.PackError) as ctx:
                cp.read_pack("widget")
            self.assertIn("cost_usd", str(ctx.exception))

    def test_dangling_escalation_template_is_rejected(self):
        files = dict(MINIMAL_PACK)
        files["policy.yaml"] += "  template: role-packs/widget/templates/gone.md\n"
        with PackFixture(files):
            with self.assertRaises(cp.PackError) as ctx:
                cp.read_pack("widget")
            self.assertIn("does not exist", str(ctx.exception))

    def test_invalid_yaml_names_the_file(self):
        files = dict(MINIMAL_PACK)
        files["tools.yaml"] = "shell:\n  allow:\n   - [unclosed\n"
        with PackFixture(files):
            with self.assertRaises(cp.PackError) as ctx:
                cp.read_pack("widget")
            self.assertIn("tools.yaml", str(ctx.exception))
            self.assertIn("invalid YAML", str(ctx.exception))


class TestBashRuleMapping(unittest.TestCase):
    def test_exact_command(self):
        self.assertEqual(cp.to_bash_rule("git status"), "Bash(git status)")

    def test_trailing_wildcard_becomes_prefix_rule(self):
        self.assertEqual(cp.to_bash_rule("git log*"), "Bash(git log:*)")

    def test_interior_wildcard_is_unmappable(self):
        # Silently dropping this would turn a deny rule into nothing at all.
        self.assertIsNone(cp.to_bash_rule("git push*--force*"))


class TestClaudeCodeOutput(unittest.TestCase):
    def test_artifacts_and_permissions(self):
        with PackFixture(MINIMAL_PACK) as fx:
            fx.add_skill("do-things", "# Skill\n\nBody text.\n")
            out = cp.compile_claude_code(cp.read_pack("widget"))

        self.assertIn("system-prompt.md", out)
        self.assertIn("settings.json", out)

        import json

        settings = json.loads(out["settings.json"])
        self.assertIn("Bash(git status)", settings["permissions"]["allow"])
        self.assertIn("Bash(git log:*)", settings["permissions"]["allow"])
        # The unmappable deny is reported, not swallowed.
        self.assertEqual(settings["permissions"]["deny"], [])
        self.assertIn("UNMAPPABLE.md", out)
        self.assertIn("git push*--force*", out["UNMAPPABLE.md"])

    def test_harness_attribution_is_off(self):
        # A harness Co-Authored-By after a blank line splits the trailer
        # block and fails dod (#282). Empty strings, never `false`: older
        # Claude Code rejects `false` and drops the whole settings file.
        import json

        with PackFixture(MINIMAL_PACK):
            settings = json.loads(cp.compile_claude_code(cp.read_pack("widget"))["settings.json"])
        self.assertEqual(settings["attribution"], {"commit": "", "pr": ""})

    def test_prompt_contains_charter_budget_and_skills(self):
        with PackFixture(MINIMAL_PACK) as fx:
            fx.add_skill("do-things", "# Skill\n\nDistinctive skill body.\n")
            prompt = cp.compile_claude_code(cp.read_pack("widget"))["system-prompt.md"]

        self.assertIn("Do widget things.", prompt)          # charter
        self.assertIn("Turns: 10", prompt)                  # budget
        self.assertIn("Cost ceiling: $1.5", prompt)         # the enforced line
        self.assertIn("push_to_default_branch", prompt)     # forbidden
        self.assertIn("budget_breach", prompt)              # hitl trigger
        self.assertIn("Distinctive skill body.", prompt)    # skills


class TestSkills(unittest.TestCase):
    """Skills reach a claude-code session as SKILL.md files it loads on
    demand by description (#320), so the description is load-bearing."""

    def compile_skill(self, frontmatter, name="do-things", body="# Skill\n\nBody text.\n"):
        with PackFixture(MINIMAL_PACK) as fx:
            fx.add_skill(name, body, frontmatter)
            return cp.compile_claude_code(cp.read_pack("widget"))

    def test_each_skill_compiles_to_a_skill_md(self):
        out = self.compile_skill("description: Use when doing widget things.\n",
                                 body="# Skill\n\nDistinctive skill body.\n")
        skill_md = out["skills/do-things/SKILL.md"]
        self.assertTrue(skill_md.startswith("---\n"))
        import yaml
        front, body = skill_md[4:].split("\n---\n", 1)
        self.assertEqual(yaml.safe_load(front),
                         {"name": "do-things", "description": "Use when doing widget things."})
        self.assertIn("Distinctive skill body.", body)

    def test_frontmatter_stays_out_of_the_role_doc(self):
        out = self.compile_skill("description: Use when doing widget things.\n",
                                 body="# Skill\n\nDistinctive skill body.\n")
        self.assertIn("Distinctive skill body.", out["system-prompt.md"])
        self.assertNotIn("description:", out["system-prompt.md"])

    def test_a_folded_description_is_one_line(self):
        out = self.compile_skill("description: >-\n  Use when doing\n  widget things.\n")
        self.assertIn("description: Use when doing widget things.\n",
                      out["skills/do-things/SKILL.md"])

    def test_a_skill_without_frontmatter_is_rejected(self):
        with self.assertRaisesRegex(cp.PackError, r"do-things\.md: no frontmatter"):
            self.compile_skill(None)

    def test_a_skill_without_a_description_is_rejected(self):
        for fm in ("title: Widget\n", "description: ''\n", "description: [a, b]\n"):
            with self.subTest(frontmatter=fm):
                with self.assertRaisesRegex(cp.PackError, "has no `description`"):
                    self.compile_skill(fm)

    def test_an_overlong_description_is_rejected(self):
        with self.assertRaisesRegex(cp.PackError, "1025 characters; the limit is 1024"):
            self.compile_skill(f"description: {'x' * 1025}\n")

    def test_invalid_frontmatter_names_the_file(self):
        with self.assertRaisesRegex(cp.PackError, r"do-things\.md: invalid frontmatter"):
            self.compile_skill("description: [unclosed\n")

    def test_a_skill_name_must_be_hyphenated_lowercase(self):
        for name in ("Do-Things", "do_things", "-do", "do--things"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(cp.PackError, "must be lowercase words"):
                    self.compile_skill("description: Use it.\n", name=name)

    def test_other_harnesses_get_no_skill_files(self):
        with PackFixture(MINIMAL_PACK) as fx:
            fx.add_skill("do-things", "# Skill\n\nBody text.\n")
            pack = cp.read_pack("widget")
            for harness in ("codex", "opencode"):
                with self.subTest(harness=harness):
                    out = cp.HARNESSES[harness](pack)
                    self.assertFalse([k for k in out if k.startswith("skills/")])

    def test_main_writes_skill_files_into_their_directories(self):
        with PackFixture(MINIMAL_PACK) as fx:
            fx.add_skill("do-things", "# Skill\n\nBody text.\n")
            out_dir = fx.tmp / "out"
            argv = sys.argv
            sys.argv = ["compile-pack.py", "--role", "widget", "--out", str(out_dir)]
            try:
                import contextlib, io
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(cp.main(), 0)
            finally:
                sys.argv = argv
            self.assertTrue((out_dir / "widget/claude-code/skills/do-things/SKILL.md").is_file())


class TestCodexOutput(unittest.TestCase):
    def test_artifacts_and_permission_mapping(self):
        with PackFixture(MINIMAL_PACK) as fx:
            fx.add_skill("do-things", "# Skill\n\nBody text.\n")
            out = cp.compile_codex(cp.read_pack("widget"))

        self.assertIn("AGENTS.md", out)
        self.assertIn("sandbox-policy.toml", out)
        self.assertIn("token-secret", out)
        self.assertIn("dispatchable-from", out)

        # Codex's sandbox has no per-command allow/deny control at all, so
        # every tools.yaml shell rule is reported as unmappable — not just
        # the interior-wildcard one that trips up Claude Code too.
        self.assertIn("UNMAPPABLE.md", out)
        self.assertIn("git push*--force*", out["UNMAPPABLE.md"])
        self.assertIn("git status", out["UNMAPPABLE.md"])
        self.assertIn("git log*", out["UNMAPPABLE.md"])

        self.assertIn("sandbox_mode", out["sandbox-policy.toml"])
        self.assertIn("approval_policy", out["sandbox-policy.toml"])

    def test_prompt_contains_charter_budget_and_skills(self):
        with PackFixture(MINIMAL_PACK) as fx:
            fx.add_skill("do-things", "# Skill\n\nDistinctive skill body.\n")
            agents_md = cp.compile_codex(cp.read_pack("widget"))["AGENTS.md"]

        self.assertIn("Do widget things.", agents_md)         # charter
        self.assertIn("Turns: 10", agents_md)                 # budget
        self.assertIn("Cost ceiling: $1.5", agents_md)        # the enforced line
        self.assertIn("push_to_default_branch", agents_md)    # forbidden
        self.assertIn("budget_breach", agents_md)              # hitl trigger
        self.assertIn("Distinctive skill body.", agents_md)   # skills


class TestOpencodeOutput(unittest.TestCase):
    def test_artifacts_and_permission_mapping(self):
        with PackFixture(MINIMAL_PACK) as fx:
            fx.add_skill("do-things", "# Skill\n\nBody text.\n")
            out = cp.compile_opencode(cp.read_pack("widget"))

        self.assertIn("AGENTS.md", out)
        self.assertIn("opencode.json", out)
        self.assertIn("token-secret", out)
        self.assertIn("dispatchable-from", out)

        # opencode's permission.bash is a real glob, so every rule —
        # including the interior wildcard that trips up both other
        # targets — maps across. Nothing is unmappable here.
        self.assertNotIn("UNMAPPABLE.md", out)

        import json

        settings = json.loads(out["opencode.json"])
        bash_perms = settings["permission"]["bash"]
        self.assertEqual(bash_perms["*"], "ask")
        self.assertEqual(bash_perms["git status"], "allow")
        self.assertEqual(bash_perms["git log*"], "allow")
        self.assertEqual(bash_perms["git push*--force*"], "deny")

    def test_prompt_contains_charter_budget_and_skills(self):
        with PackFixture(MINIMAL_PACK) as fx:
            fx.add_skill("do-things", "# Skill\n\nDistinctive skill body.\n")
            agents_md = cp.compile_opencode(cp.read_pack("widget"))["AGENTS.md"]

        self.assertIn("Do widget things.", agents_md)         # charter
        self.assertIn("Turns: 10", agents_md)                 # budget
        self.assertIn("Cost ceiling: $1.5", agents_md)        # the enforced line
        self.assertIn("push_to_default_branch", agents_md)    # forbidden
        self.assertIn("budget_breach", agents_md)              # hitl trigger
        self.assertIn("Distinctive skill body.", agents_md)   # skills


class TestEveryHarnessEmitsDispatcherArtifacts(unittest.TestCase):
    """#113: the dispatcher's shipped-nothing gate greps a compiled pack's
    `produces` file, and a missing file used to fail open (requires_pr
    silently became false). token-secret, dispatchable-from and produces
    are declared harness-agnostic — both compile_* docstrings say so for
    the first two — so every entry in HARNESSES must emit all three.
    Parameterised over HARNESSES so a new target cannot be added without
    satisfying it, the way compile_codex originally was (#109 omitted
    produces)."""

    DISPATCHER_ARTIFACTS = ("token-secret", "dispatchable-from", "produces")

    def test_every_harness_emits_the_artifacts_the_dispatcher_reads(self):
        with PackFixture(MINIMAL_PACK):
            pack = cp.read_pack("widget")
            for harness, compile_fn in cp.HARNESSES.items():
                with self.subTest(harness=harness):
                    out = compile_fn(pack)
                    for artifact in self.DISPATCHER_ARTIFACTS:
                        self.assertIn(
                            artifact, out,
                            f"{harness} does not emit `{artifact}`, which the "
                            "dispatcher's compile step reads directly"
                        )

    def test_every_harness_produces_file_reflects_pack_produces(self):
        files = dict(MINIMAL_PACK)
        files["pack.yaml"] += "produces:\n  - comments\n  - status\n"
        with PackFixture(files):
            pack = cp.read_pack("widget")
            for harness, compile_fn in cp.HARNESSES.items():
                with self.subTest(harness=harness):
                    out = compile_fn(pack)
                    self.assertNotIn("pull_request", out["produces"].splitlines())


class TestRealPacksInThisRepo(unittest.TestCase):
    """The packs actually committed here must compile. This is the check
    that fails a PR when someone edits a pack into an invalid state."""

    def test_every_committed_pack_compiles(self):
        packs_dir = REPO_ROOT / "role-packs"
        roles = sorted(p.name for p in packs_dir.iterdir() if (p / "pack.yaml").is_file())
        self.assertTrue(roles, "no role packs found — expected at least developer")
        for role in roles:
            with self.subTest(role=role):
                pack = cp.read_pack(role)
                out = cp.compile_claude_code(pack)
                self.assertTrue(out["system-prompt.md"].strip())
                self.assertTrue(pack["skills"], f"{role} has no skills/")
                for skill in pack["skills"]:
                    self.assertIn(f"skills/{skill['name']}/SKILL.md", out)

                # A pack that compiles for one harness and not the others is
                # exactly the gap REQ-003 flags: this is the check that
                # would catch it.
                codex_out = cp.compile_codex(pack)
                self.assertTrue(codex_out["AGENTS.md"].strip())

                opencode_out = cp.compile_opencode(pack)
                self.assertTrue(opencode_out["AGENTS.md"].strip())


if __name__ == "__main__":
    unittest.main(verbosity=2)
