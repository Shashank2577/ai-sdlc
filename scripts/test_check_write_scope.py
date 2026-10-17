#!/usr/bin/env python3
"""Tests for the `scope` check (ADR-0011, #322).

The scopes are the real packs' `write_scope`, read from role-packs/, so a
pack change that would let a developer write a workflow fails here, not in
production.

    python3 scripts/test_check_write_scope.py
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("check_write_scope", HERE / "check-write-scope.py")
S = importlib.util.module_from_spec(spec)
sys.modules["check_write_scope"] = S
spec.loader.exec_module(S)

SCOPES = S.load_scopes()
BOT = "foundry-ai-sdlc[bot]"


def commit(role, files, sha="a" * 40, merge=False, verified=False, author_login="", subject="change"):
    return {"sha": sha, "subject": subject, "role": role, "merge": merge, "files": files,
            "verified": verified, "author_login": author_login}


def check(commits, files=None, author=BOT, item=12, dispatched=("developer",), extras=None):
    if files is None:
        files = sorted({f for c in commits if not c["merge"] for f in c["files"]})
    return S.evaluate({"author": author, "item": item}, commits, files, SCOPES, extras or {},
                      set(dispatched))


class TestGlobs(unittest.TestCase):
    def test_double_star_reaches_any_depth(self):
        self.assertTrue(S.glob_match(".github/workflows/**", ".github/workflows/ci.yml"))
        self.assertTrue(S.glob_match("src/**", "src/a/b/c.py"))
        self.assertFalse(S.glob_match("src/**", "srcx/a.py"))

    def test_single_star_stays_in_one_segment(self):
        self.assertTrue(S.glob_match("scripts/*deploy*", "scripts/deploy-pages.py"))
        self.assertFalse(S.glob_match("scripts/*deploy*", "scripts/x/deploy.py"))
        self.assertTrue(S.glob_match("*", "package.json"))
        self.assertFalse(S.glob_match("*", "src/index.ts"))

    def test_extglob_negation_excludes_only_the_named_segment(self):
        pat = "role-packs/!(developer)/**"
        self.assertTrue(S.glob_match(pat, "role-packs/devops/policy.yaml"))
        self.assertFalse(S.glob_match(pat, "role-packs/developer/charter.md"))
        self.assertTrue(S.glob_match(pat, "role-packs/developerx/charter.md"))

    def test_literal_path(self):
        self.assertTrue(S.glob_match(".github/CODEOWNERS", ".github/CODEOWNERS"))
        self.assertFalse(S.glob_match(".github/CODEOWNERS", ".github/CODEOWNERSx"))


class TestScope(unittest.TestCase):
    def test_deny_wins_over_allow(self):
        ok, why = S.scope_allows({"allow": ["**"], "deny": ["policies/**"]}, "policies/dod.yaml")
        self.assertFalse(ok)
        self.assertIn("denied", why)

    def test_no_allow_list_fails_closed(self):
        self.assertFalse(S.scope_allows({"deny": []}, "src/a.py")[0])

    def test_real_packs_keep_workflows_to_devops(self):
        for role, scope in SCOPES.items():
            ok, _ = S.scope_allows(scope, ".github/workflows/dispatch.yml")
            self.assertEqual(ok, role == "devops", f"{role} workflow access is {ok}")


class TestProvenance(unittest.TestCase):
    def test_trailer_read_case_insensitively(self):
        self.assertEqual(S.agent_role("x\n\nWork-Item: o/r#1\nagent-role: Developer\n"), "developer")

    def test_missing_and_ambiguous_trailers(self):
        self.assertIsNone(S.agent_role("no trailers"))
        self.assertEqual(S.agent_role("Agent-Role: developer\nAgent-Role: devops"), "!ambiguous")

    def test_work_item_from_branch(self):
        self.assertEqual(S.work_item_of("story/FDY-290-product-routing"), 290)
        self.assertEqual(S.work_item_of("bug/FDY-7-x"), 7)
        self.assertIsNone(S.work_item_of("feature/thing"))

    def test_only_the_dispatcher_records_count(self):
        marker = "<!-- foundry:dispatch-start role=devops product=foundry-program run=99 -->\n### Dispatch"
        claims = S.dispatch_claims([
            {"user": {"login": "github-actions[bot]"}, "body": marker},
            {"user": {"login": BOT}, "body": marker.replace("run=99", "run=100")},
            {"user": {"login": "Shashank2577"}, "body": marker.replace("run=99", "run=101")},
        ])
        self.assertEqual(claims, [{"role": "devops", "product": "foundry-program", "run": 99}])

    def test_marker_must_open_the_comment(self):
        # A workflow that quotes agent text into a comment cannot put a
        # marker on the comment's first line.
        quoted = "> quoted\n<!-- foundry:dispatch-start role=devops product=p run=1 -->"
        self.assertEqual(S.dispatch_claims([{"user": {"login": "github-actions[bot]"}, "body": quoted}]), [])

    def test_legacy_session_start_table_is_a_record(self):
        body = ("### Dispatch — session start\n\n| | |\n|---|---|\n"
                "| Product | `foundry-program` (`Shashank2577/ai-sdlc`) |\n| Role | `qa` |\n"
                "| Run | https://github.com/Shashank2577/ai-sdlc/actions/runs/123 |\n")
        self.assertEqual(S.dispatch_claims([{"user": {"login": "github-actions[bot]"}, "body": body}]),
                         [{"role": "qa", "product": "foundry-program", "run": 123}])

    def test_run_must_be_dispatch_yml_for_this_item_role_and_product(self):
        run = {"path": ".github/workflows/dispatch.yml", "event": "workflow_dispatch"}
        jobs = [{"name": "#12 as devops on foundry-program"}]
        self.assertTrue(S.run_matches(run, jobs, 12, "devops", "foundry-program"))
        self.assertFalse(S.run_matches(run, jobs, 12, "developer", "foundry-program"))
        self.assertFalse(S.run_matches(run, jobs, 13, "devops", "foundry-program"))
        self.assertFalse(S.run_matches({**run, "path": ".github/workflows/other.yml"}, jobs, 12,
                                       "devops", "foundry-program"))
        self.assertFalse(S.run_matches({**run, "event": "push"}, jobs, 12, "devops", "foundry-program"))
        self.assertFalse(S.run_matches(None, jobs, 12, "devops", "foundry-program"))


class TestEvaluate(unittest.TestCase):
    def test_developer_in_scope_passes(self):
        v = check([commit("developer", ["scripts/assign.py", "src/app.py"])])
        self.assertTrue(v["ok"], v["violations"])

    def test_devops_dispatch_may_change_a_workflow(self):
        v = check([commit("devops", [".github/workflows/ci.yml"])], dispatched={"devops"})
        self.assertTrue(v["ok"], v["violations"])

    def test_developer_workflow_edit_fails_even_if_dispatched(self):
        v = check([commit("developer", [".github/workflows/ci.yml"])])
        self.assertFalse(v["ok"])
        self.assertTrue(any("only a devops dispatch" in x for x in v["violations"]))

    def test_forged_devops_trailer_without_a_devops_dispatch_fails(self):
        v = check([commit("devops", [".github/workflows/ci.yml"])], dispatched={"developer"})
        self.assertFalse(v["ok"])
        self.assertTrue(any("no `devops` session was dispatched" in x for x in v["violations"]))

    def test_write_scope_deny_fails(self):
        v = check([commit("developer", ["policies/dod.yaml"])])
        self.assertFalse(v["ok"])
        self.assertTrue(any("denied by `policies/**`" in x for x in v["violations"]))

    def test_outside_allow_list_fails(self):
        v = check([commit("architect", ["scripts/x.py"])], dispatched={"architect"})
        self.assertFalse(v["ok"])

    def test_product_extra_opens_a_path_but_never_a_denied_one(self):
        extras = {"developer": ["package.json", ".github/**"]}
        self.assertTrue(check([commit("developer", ["package.json"])], extras=extras)["ok"])
        self.assertFalse(check([commit("developer", [".github/dependabot.yml"])], extras=extras)["ok"])

    def test_no_dispatch_record_fails(self):
        v = check([commit("developer", ["src/a.py"])], dispatched=())
        self.assertFalse(v["ok"])
        self.assertTrue(any("dispatched: none" in x for x in v["violations"]))

    def test_agent_role_without_a_work_item_branch_fails(self):
        v = check([commit("developer", ["src/a.py"])], item=None)
        self.assertFalse(v["ok"])

    def test_missing_trailer_fails(self):
        self.assertFalse(check([commit(None, ["src/a.py"])])["ok"])

    def test_human_pr_is_not_scope_checked(self):
        v = check([commit("human", [".github/workflows/ci.yml", "policies/dod.yaml"])],
                  author="Shashank2577", item=None, dispatched=())
        self.assertTrue(v["ok"], v["violations"])

    def test_agent_commits_on_a_human_pr_are_still_checked(self):
        # The PAT era: agent PRs are authored by the owner's account, so the
        # trailer, not the author, is what marks an agent commit.
        v = check([commit("developer", [".github/workflows/ci.yml"])], author="Shashank2577")
        self.assertFalse(v["ok"])

    def test_unverified_human_commit_on_a_bot_pr_fails(self):
        v = check([commit("developer", ["src/a.py"]),
                   commit("human", ["policies/dod.yaml"], sha="b" * 40)])
        self.assertFalse(v["ok"])
        self.assertTrue(any("verified its signature" in x for x in v["violations"]))

    def test_verified_human_commit_on_a_bot_pr_passes(self):
        v = check([commit("developer", ["src/a.py"]),
                   commit("human", ["policies/dod.yaml"], sha="b" * 40, verified=True,
                          author_login="Shashank2577")])
        self.assertTrue(v["ok"], v["violations"])

    def test_change_only_in_a_merge_commit_fails(self):
        v = check([commit("developer", ["src/a.py"]),
                   commit(None, [".github/workflows/ci.yml"], sha="c" * 40, merge=True)],
                  files=["src/a.py", ".github/workflows/ci.yml"])
        self.assertFalse(v["ok"])
        self.assertTrue(any("only in a merge commit" in x for x in v["violations"]))

    def test_merge_commit_bringing_in_main_is_fine_when_net_diff_is_attributed(self):
        v = check([commit("developer", ["src/a.py"]),
                   commit(None, ["policies/dod.yaml"], sha="c" * 40, merge=True)],
                  files=["src/a.py"])
        self.assertTrue(v["ok"], v["violations"])

    def test_render_names_every_violation(self):
        v = check([commit("developer", ["policies/a.yaml", ".github/workflows/b.yml"])])
        text = S.render(v)
        self.assertIn("<!-- foundry:scope -->", text)
        self.assertEqual(text.count("\n- "), len(v["violations"]))


if __name__ == "__main__":
    unittest.main(verbosity=1)
