#!/usr/bin/env python3
"""Tests for the refinement trigger.

`should_refine()` and `plan_refill()` are pure functions of the board, so
the whole decision — quiet vs. dispatch vs. wait vs. create — is testable
without a repository. The case that matters most: above the floor, the
plan is `quiet`, and quiet means the caller makes no `gh` call at all —
this runs hourly.

    python3 scripts/test_refine.py
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("refine", HERE / "refine.py")
R = importlib.util.module_from_spec(spec)
sys.modules["refine"] = R
spec.loader.exec_module(R)


def pm_issue(number, *labels):
    return {"number": number, "labels": list(labels)}


class TestShouldRefine(unittest.TestCase):
    def test_above_the_floor_does_not_refine(self):
        self.assertFalse(R.should_refine(2, 1))

    def test_at_the_floor_refines(self):
        self.assertTrue(R.should_refine(1, 1))

    def test_below_the_floor_refines(self):
        self.assertTrue(R.should_refine(0, 1))

    def test_a_zero_floor_only_fires_on_a_fully_empty_queue(self):
        self.assertFalse(R.should_refine(1, 0))
        self.assertTrue(R.should_refine(0, 0))


class TestPlanRefill(unittest.TestCase):
    def test_above_the_floor_is_quiet_regardless_of_the_board(self):
        p = R.plan_refill(5, 1, [pm_issue(9, "status:ready")])
        self.assertEqual(p["action"], "quiet")

    def test_at_the_floor_with_no_pm_work_creates_one(self):
        p = R.plan_refill(1, 1, [])
        self.assertEqual(p["action"], "create")

    def test_at_the_floor_with_a_ready_pm_item_dispatches_it(self):
        p = R.plan_refill(1, 1, [pm_issue(9, "status:ready")])
        self.assertEqual(p["action"], "dispatch")
        self.assertEqual(p["number"], 9)

    def test_at_the_floor_with_an_unapproved_pm_item_waits(self):
        p = R.plan_refill(0, 1, [pm_issue(9, "status:needs-refinement")])
        self.assertEqual(p["action"], "wait")
        self.assertEqual(p["number"], 9)

    def test_an_in_progress_pm_item_is_waited_on_not_duplicated(self):
        p = R.plan_refill(0, 1, [pm_issue(9, "status:in-progress")])
        self.assertEqual(p["action"], "wait")

    def test_the_lowest_ready_pm_item_is_chosen_when_several_exist(self):
        p = R.plan_refill(0, 1, [pm_issue(9, "status:ready"), pm_issue(4, "status:ready")])
        self.assertEqual(p["number"], 4)

    def test_a_ready_item_wins_over_an_earlier_unapproved_one(self):
        # Dispatching real, approved work beats waiting on an earlier item
        # nobody has cleared yet.
        p = R.plan_refill(0, 1, [pm_issue(2, "status:needs-refinement"),
                                 pm_issue(7, "status:ready")])
        self.assertEqual(p["action"], "dispatch")
        self.assertEqual(p["number"], 7)

    def test_the_same_board_always_gives_the_same_plan(self):
        board = [pm_issue(9, "status:ready"), pm_issue(4, "status:needs-refinement")]
        first = R.plan_refill(0, 1, board)
        second = R.plan_refill(0, 1, list(reversed(board)))
        self.assertEqual(first, second)


class TestReport(unittest.TestCase):
    def test_the_report_names_the_decision(self):
        p = R.plan_refill(0, 1, [])
        report = R.render_plan(p, "policy.yaml")
        self.assertIn("create", report)
        self.assertIn("floor 1", report)


class TestPolicyLoading(unittest.TestCase):
    def test_the_committed_policy_loads_and_is_bounded(self):
        policy, source = R.load_refill_policy()
        self.assertIn("orchestrator/policy.yaml", source)
        self.assertGreaterEqual(policy["ready_floor"], 0)
        self.assertEqual(policy["role"], "product-manager")
        self.assertEqual(policy["scope_source"], "requirements/coverage.yaml")

    def test_a_missing_policy_falls_back_to_something_conservative(self):
        policy, source = R.load_refill_policy(Path("/nonexistent/policy.yaml"))
        self.assertIn("fallback", source)
        self.assertEqual(policy["ready_floor"], 1)

    def test_a_negative_floor_is_rejected(self, tmp_path=None):
        # A broken policy read must not become an unbounded loop: a
        # negative floor is nonsensical, so this fails loud at load time
        # rather than silently disabling refinement forever.
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "policy.yaml"
            bad.write_text("refill:\n  ready_floor: -1\n")
            with self.assertRaises(SystemExit):
                R.load_refill_policy(bad)


if __name__ == "__main__":
    unittest.main(verbosity=2)
