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


class TestExpectedRoles(unittest.TestCase):
    """`PRD_ROLES` used to be a Python literal that named a pack
    (`delivery-manager`) which has never existed, so `roles_built` read
    7/8 for the whole programme (#185). The expected list now lives in
    requirements/coverage.yaml; this is the test that would have caught
    the day the mismatch was introduced instead of a client reading the
    wrong number.
    """

    def test_expected_roles_is_not_a_python_literal(self):
        expected = S.load_expected_roles()
        self.assertTrue(expected)
        self.assertNotIn("delivery-manager", expected)
        self.assertIn("delivery-lead", expected)

    def test_expected_roles_matches_the_packs_on_disk_in_both_directions(self):
        expected = set(S.load_expected_roles())
        built = {p.name for p in (REPO_ROOT / "role-packs").iterdir()
                 if p.is_dir() and (p / "pack.yaml").is_file()}
        missing_packs = expected - built
        unlisted_packs = built - expected
        self.assertEqual(
            missing_packs, set(),
            f"requirements/coverage.yaml expects a role pack that does not "
            f"exist: {missing_packs}")
        self.assertEqual(
            unlisted_packs, set(),
            f"role pack(s) on disk have no entry in requirements/coverage.yaml "
            f"policy.roles.expected: {unlisted_packs}")

    def test_roles_built_is_eight_of_eight_with_the_packs_as_they_are_today(self):
        facts = S.collect_facts(False, S.load_expected_roles())
        self.assertEqual(len(facts["roles_built"]), 8)
        self.assertEqual(len(facts["roles_expected"]), 8)
        self.assertEqual(facts["roles_unexpected"], [])

    def test_an_entry_with_no_pack_is_still_reported_as_missing(self):
        facts = S.collect_facts(False, ["orchestrator", "phantom-role"])
        self.assertIn("orchestrator", facts["roles_built"])
        self.assertNotIn("phantom-role", facts["roles_built"])

    def test_a_pack_with_no_entry_in_the_expected_list_is_reported_not_ignored(self):
        facts = S.collect_facts(False, ["orchestrator"])
        self.assertIn("qa", facts["roles_unexpected"])


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


class TestSelfHostingVerdict(unittest.TestCase):
    """The verdict is computed against a reviewable threshold, not hardcoded.

    Two claims, not one: "the machinery works at all" (one delivered PR) and
    "self-hosting is the practice" (a threshold set in coverage.yaml, an
    order of magnitude past the floor so one lucky run cannot pass it).
    """

    POLICY = {"machinery_at_least": 1, "practice_at_least": 10}

    def test_zero_delivered_is_unproven_machinery(self):
        v = S.self_hosting_verdict({"agent_delivered_prs": 0, "merged_prs": 0}, self.POLICY)
        self.assertFalse(v["machinery_proven"])
        self.assertFalse(v["practice_proven"])

    def test_below_practice_threshold_is_proven_machinery_only(self):
        v = S.self_hosting_verdict({"agent_delivered_prs": 9, "merged_prs": 20}, self.POLICY)
        self.assertTrue(v["machinery_proven"])
        self.assertFalse(v["practice_proven"],
                         "9 delivered PRs is one short of the practice threshold of 10")

    def test_at_practice_threshold_is_proven_practice(self):
        v = S.self_hosting_verdict({"agent_delivered_prs": 10, "merged_prs": 20}, self.POLICY)
        self.assertTrue(v["machinery_proven"])
        self.assertTrue(v["practice_proven"],
                        "10 delivered PRs meets the practice threshold of 10")

    def test_threshold_lives_in_coverage_yaml_not_a_python_literal(self):
        policy = S.load_self_hosting_policy()
        self.assertIn("machinery_at_least", policy)
        self.assertIn("practice_at_least", policy)
        self.assertGreater(policy["practice_at_least"], policy["machinery_at_least"],
                           "the practice claim must require more evidence than the "
                           "machinery claim, or the two collapse into one")


class TestNoteContradictsChecks(unittest.TestCase):
    """The mechanism #159 asked for: a `notes:` field that denies work the
    requirement's own checks say exists. Eight of fourteen notes had drifted
    into exactly this state — each accurate when written, none revisited."""

    def test_a_stale_unproven_note_on_a_scoring_requirement_is_flagged(self):
        self.assertIsNotNone(S.note_contradicts_checks(
            "No dispatched session has yet produced a merged PR; unproven.", 100))

    def test_a_nothing_built_note_on_a_scoring_requirement_is_flagged(self):
        self.assertIsNotNone(S.note_contradicts_checks("Nothing built.", 67))

    def test_a_no_x_exists_note_on_a_scoring_requirement_is_flagged(self):
        self.assertIsNotNone(S.note_contradicts_checks(
            "No adapter layer exists; the sync talks to GitHub directly.", 100))

    def test_a_zero_scoring_requirement_correctly_saying_nothing_is_built_is_not_flagged(self):
        # This is the case the mechanism must NOT catch: the note is telling
        # the truth. A requirement that scores 0% and says so is accurate,
        # not stale.
        self.assertIsNone(S.note_contradicts_checks("Nothing built.", 0))

    def test_a_note_with_no_denial_phrase_is_not_flagged(self):
        self.assertIsNone(S.note_contradicts_checks(
            "Two of three named harnesses are implemented.", 100))

    def test_an_empty_note_is_not_flagged(self):
        self.assertIsNone(S.note_contradicts_checks("", 100))


class TestRender(unittest.TestCase):
    POLICY = {"machinery_at_least": 1, "practice_at_least": 10}
    NO_ROLES = {"roles_built": [], "roles_expected": [], "roles_unexpected": []}

    def test_banner_states_the_unproven_machinery_claim_and_its_threshold(self):
        cov = S.evaluate(S.load_coverage(), REPO_ROOT, {"agent_delivered_prs": 0})
        html = S.render(cov, None, {**self.NO_ROLES, "ceremonies_built": [],
                                    "dirs_present": [], "agent_delivered_prs": 0,
                                    "merged_prs": 12, "dispatch_runs": {}},
                        {"repo": "a/b"}, self.POLICY)
        self.assertIn("Self-hosting is unproven", html)
        self.assertIn("0 have been", html)
        self.assertIn("threshold is 1", html)

    def test_banner_distinguishes_proven_machinery_from_unproven_practice(self):
        cov = S.evaluate(S.load_coverage(), REPO_ROOT, {"agent_delivered_prs": 3})
        html = S.render(cov, None, {**self.NO_ROLES, "ceremonies_built": [],
                                    "dirs_present": [], "agent_delivered_prs": 3,
                                    "merged_prs": 12, "dispatch_runs": {}},
                        {"repo": "a/b"}, self.POLICY)
        self.assertIn("machinery is proven", html)
        self.assertIn("practice is not yet", html)
        self.assertIn("threshold of 10", html)

    def test_banner_states_practice_proven_once_past_threshold(self):
        cov = S.evaluate(S.load_coverage(), REPO_ROOT, {"agent_delivered_prs": 46})
        html = S.render(cov, None, {**self.NO_ROLES, "ceremonies_built": [],
                                    "dirs_present": [], "agent_delivered_prs": 46,
                                    "merged_prs": 73, "dispatch_runs": {}},
                        {"repo": "a/b"}, self.POLICY)
        self.assertIn("proven, as machinery and as practice", html)

    def test_contradiction_is_surfaced_on_the_page(self):
        cov = {"REQ-001": {"summary": "s", "notes": "Nothing built.", "pct": 50,
                           "passed": 1, "total": 2, "checks": [],
                           "contradiction": "nothing built"}}
        html = S.render(cov, None, {**self.NO_ROLES, "ceremonies_built": [],
                                    "dirs_present": [], "agent_delivered_prs": 0,
                                    "merged_prs": 0, "dispatch_runs": {}},
                        {"repo": "a/b"}, self.POLICY)
        self.assertIn("contradict their own checks", html)
        self.assertIn("REQ-001", html)

    def test_an_unexpected_pack_is_shown_on_the_page_not_dropped(self):
        cov = S.evaluate(S.load_coverage(), REPO_ROOT, {"agent_delivered_prs": 0})
        html = S.render(cov, None, {"roles_built": ["qa"], "roles_expected": ["qa"],
                                    "roles_unexpected": ["mystery-role"],
                                    "ceremonies_built": [], "dirs_present": [],
                                    "agent_delivered_prs": 0, "merged_prs": 0,
                                    "dispatch_runs": {}},
                        {"repo": "a/b"}, self.POLICY)
        self.assertIn("mystery-role", html)
        self.assertIn("not in the expected list", html)

    def test_self_contained_and_escaped(self):
        cov = {"REQ-001": {"summary": "<script>x</script>", "notes": "", "checks": []}}
        html = S.render(S.evaluate(cov, REPO_ROOT, {}), None,
                        {**self.NO_ROLES, "ceremonies_built": [], "dirs_present": [],
                         "agent_delivered_prs": 0, "merged_prs": 0, "dispatch_runs": {}},
                        {"repo": "a/b"}, self.POLICY)
        self.assertNotIn("<script>x", html)
        self.assertNotIn("http://", html.split("<style>")[1].split("</style>")[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
