#!/usr/bin/env python3
"""Tests for the programme status generator.

The property this page exists to hold: it must not be able to flatter the
programme. Every test here is a way that could happen — a check that
passes when it should not, an unknown check kind treated as satisfied, a
"traced" status leaking into the "satisfied" column.

    python3 dashboards/test_status.py
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
sys.path.insert(0, str(HERE))

spec = importlib.util.spec_from_file_location("dash_status", HERE / "status.py")
S = importlib.util.module_from_spec(spec)
sys.modules["dash_status"] = S
spec.loader.exec_module(S)


class TestChecks(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "scripts").mkdir()
        (self.root / "scripts" / "thing.py").write_text("def compile_claude_code():\n    pass\n")
        (self.root / "packs").mkdir()
        (self.root / "packs" / "a.yaml").write_text("provisioned: false\n")
        (self.root / "packs" / "b.yaml").write_text("provisioned: false\n")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def check(self, spec, facts=None):
        return S.run_check(spec, self.root, facts or {})

    def test_exists(self):
        self.assertTrue(self.check({"exists": "scripts/thing.py"})[0])
        self.assertFalse(self.check({"exists": "scripts/nope.py"})[0])

    def test_glob(self):
        self.assertTrue(self.check({"glob": "scripts/*.py"})[0])
        self.assertFalse(self.check({"glob": "infra/**"})[0])

    def test_count_reports_what_it_found(self):
        ok, text = self.check({"count": {"glob": "packs/*.yaml", "at_least": 8}})
        self.assertFalse(ok)
        self.assertIn("found 2", text)

    def test_count_passes_at_the_threshold(self):
        self.assertTrue(self.check({"count": {"glob": "packs/*.yaml", "at_least": 2}})[0])

    def test_grep(self):
        self.assertTrue(self.check(
            {"grep": {"glob": "scripts/*.py", "pattern": "compile_claude_code"}})[0])
        self.assertFalse(self.check(
            {"grep": {"glob": "scripts/*.py", "pattern": "compile_codex"}})[0])

    def test_grep_survives_an_unreadable_file(self):
        (self.root / "scripts" / "binary.py").write_bytes(b"\xff\xfe\x00\x01")
        ok, _ = self.check({"grep": {"glob": "scripts/*.py", "pattern": "compile_claude_code"}})
        self.assertTrue(ok, "one undecodable file must not hide a real match")

    def test_delivered_by_agent_reads_the_measured_fact(self):
        self.assertFalse(self.check({"delivered_by_agent": 1}, {"agent_delivered_prs": 0})[0])
        self.assertTrue(self.check({"delivered_by_agent": 1}, {"agent_delivered_prs": 3})[0])

    def test_an_unknown_check_kind_fails_rather_than_passes(self):
        # The failure mode that matters: a typo in coverage.yaml silently
        # counting as satisfied would inflate every number on the page.
        ok, text = self.check({"someday": "maybe"})
        self.assertFalse(ok)
        self.assertIn("unknown check kind", text)


class TestEvaluate(unittest.TestCase):
    def test_percentage_is_the_fraction_of_checks_that_pass(self):
        root = Path(tempfile.mkdtemp())
        (root / "a").write_text("x")
        cov = {"REQ-001": {"summary": "s", "checks": [
            {"exists": "a"}, {"exists": "b"}, {"exists": "c"}, {"exists": "d"}]}}
        out = S.evaluate(cov, root, {})
        self.assertEqual(out["REQ-001"]["passed"], 1)
        self.assertEqual(out["REQ-001"]["total"], 4)
        self.assertEqual(out["REQ-001"]["pct"], 25)
        shutil.rmtree(root, ignore_errors=True)

    def test_a_requirement_with_no_checks_is_zero_not_a_crash(self):
        out = S.evaluate({"REQ-999": {"summary": "s", "checks": []}}, Path("/tmp"), {})
        self.assertEqual(out["REQ-999"]["pct"], 0)


class TestAgainstThisRepo(unittest.TestCase):
    def test_every_requirement_in_the_index_has_coverage_criteria(self):
        # A requirement with no criteria would silently vanish from the page.
        index = (REPO_ROOT / "requirements" / "index.md").read_text()
        ids = {line.split("|")[1].strip() for line in index.splitlines()
               if line.strip().startswith("| REQ-")}
        cov = S.load_coverage()
        self.assertTrue(ids)
        self.assertEqual(ids - set(cov), set(),
                         "requirements with no entry in coverage.yaml")

    def test_the_committed_criteria_all_parse(self):
        cov = S.load_coverage()
        for req, spec in cov.items():
            for check in spec.get("checks", []):
                with self.subTest(req=req, check=check):
                    _, text = S.run_check(check, REPO_ROOT, {"agent_delivered_prs": 0})
                    self.assertNotIn("unknown check kind", text)

    def test_the_page_does_not_claim_more_than_the_repo_has(self):
        """No requirement may report a higher score than its checks earn.

        This used to pin literals — REQ-008 == 0 "no client layer exists",
        REQ-010 == 0, REQ-013 == 0. Good intent, wrong shape: the assertions
        described a snapshot, so the test failed the moment the work was
        actually built. `scripts/transcript-to-prd.py` landed, REQ-008 went
        0 -> 33, and a green suite turned red on success.

        The literals were standing in for an invariant, so assert the
        invariant instead: for every requirement, re-run its checks directly
        against the filesystem and confirm the reported percentage is not
        higher than what independently passes. Flattery still fails —
        which is the whole point of this page — and progress no longer does.
        """
        coverage = S.load_coverage()
        facts = {"agent_delivered_prs": 0}
        cov = S.evaluate(coverage, REPO_ROOT, facts)
        for req, spec in coverage.items():
            checks = spec.get("checks", [])
            with self.subTest(req=req):
                if not checks:
                    self.assertEqual(cov[req]["pct"], 0,
                                     "a requirement with no criteria cannot score")
                    continue
                passing = sum(1 for c in checks
                              if S.run_check(c, REPO_ROOT, facts)[0])
                earned = round(100 * passing / len(checks))
                self.assertLessEqual(
                    cov[req]["pct"], earned,
                    f"{req} reports {cov[req]['pct']}% but only {passing} of "
                    f"{len(checks)} criteria pass when re-run independently")

    def test_a_requirement_cannot_read_complete_unless_every_check_passes(self):
        # The other direction of the same guard: 100% must mean every
        # criterion actually passes, not that the arithmetic rounded up.
        coverage = S.load_coverage()
        facts = {"agent_delivered_prs": 0}
        cov = S.evaluate(coverage, REPO_ROOT, facts)
        for req, spec in coverage.items():
            if cov[req]["pct"] != 100:
                continue
            with self.subTest(req=req):
                for check in spec.get("checks", []):
                    ok, text = S.run_check(check, REPO_ROOT, facts)
                    self.assertTrue(ok, f"{req} reads 100% but {text} fails")

    def test_self_hosting_cannot_read_complete_without_a_delivered_pr(self):
        cov = S.evaluate(S.load_coverage(), REPO_ROOT, {"agent_delivered_prs": 0})
        self.assertLess(cov["REQ-014"]["pct"], 100,
                        "self-hosting must not read as done until an agent "
                        "session has actually delivered a merged PR")


class TestRender(unittest.TestCase):
    def test_banner_states_the_unproven_claim(self):
        cov = S.evaluate(S.load_coverage(), REPO_ROOT, {"agent_delivered_prs": 0})
        html = S.render(cov, None, {"roles_built": [], "ceremonies_built": [],
                                    "dirs_present": [], "agent_delivered_prs": 0,
                                    "merged_prs": 12, "dispatch_runs": {}}, {"repo": "a/b"})
        self.assertIn("Self-hosting is unproven", html)
        self.assertIn("0 merged pull request(s)", html)

    def test_self_contained_and_escaped(self):
        cov = {"REQ-001": {"summary": "<script>x</script>", "notes": "", "checks": []}}
        html = S.render(S.evaluate(cov, REPO_ROOT, {}), None,
                        {"roles_built": [], "ceremonies_built": [], "dirs_present": [],
                         "agent_delivered_prs": 0, "merged_prs": 0, "dispatch_runs": {}},
                        {"repo": "a/b"})
        self.assertNotIn("<script>x", html)
        self.assertNotIn("http://", html.split("<style>")[1].split("</style>")[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
