#!/usr/bin/env python3
"""Tests for the sprint planning ceremony generator.

`trailing_capacity` and `build_plan` are pure — velocity/ready-queue/risk
data in, plan out — so capacity, scope and the cut line are all testable
without a repository, the same style as `scripts/test_refine.py` and
`scripts/test_retro.py`.

    python3 scripts/test_plan.py
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("plan", HERE / "plan.py")
P = importlib.util.module_from_spec(spec)
sys.modules["plan"] = P
spec.loader.exec_module(P)


def ready(number, title="Story"):
    return {"number": number, "title": title, "url": f"https://x/{number}"}


def week(closed, start="2026-08-01", end="2026-08-08"):
    return {"week_start": start, "week_end": end, "closed": closed}


class TestTrailingCapacity(unittest.TestCase):
    def test_no_history_returns_none_and_states_why(self):
        capacity, source = P.trailing_capacity([])
        self.assertIsNone(capacity)
        self.assertIn("no closed stories", source)

    def test_all_zero_weeks_returns_none(self):
        capacity, _ = P.trailing_capacity([week(0), week(0), week(0)])
        self.assertIsNone(capacity)

    def test_averages_trailing_weeks_rounded(self):
        capacity, source = P.trailing_capacity([week(2), week(3), week(4)], weeks=3)
        self.assertEqual(capacity, 3)  # (2+3+4)/3 = 3
        self.assertIn("dashboards/burndown.py", source)

    def test_only_uses_the_trailing_n_weeks(self):
        # An old zero week outside the trailing window must not drag the
        # average down.
        capacity, _ = P.trailing_capacity([week(0), week(4), week(4)], weeks=2)
        self.assertEqual(capacity, 4)

    def test_capacity_is_never_zero(self):
        capacity, _ = P.trailing_capacity([week(0), week(0), week(1)], weeks=3)
        self.assertGreaterEqual(capacity, 1)


class TestBuildPlan(unittest.TestCase):
    def test_assumed_capacity_is_flagged_and_defaults_to_one(self):
        plan = P.build_plan([ready(1), ready(2)], [], [])
        self.assertTrue(plan["capacity_assumed"])
        self.assertEqual(plan["capacity"], 1)
        self.assertEqual([i["number"] for i in plan["scope"]], [1])
        self.assertEqual([i["number"] for i in plan["cut_line"]], [2])

    def test_scope_takes_the_first_n_by_capacity(self):
        plan = P.build_plan([ready(1), ready(2), ready(3)], [], [week(2), week(2)])
        self.assertEqual(plan["capacity"], 2)
        self.assertFalse(plan["capacity_assumed"])
        self.assertEqual([i["number"] for i in plan["scope"]], [1, 2])
        self.assertEqual([i["number"] for i in plan["cut_line"]], [3])

    def test_empty_ready_queue_is_empty_scope_not_an_error(self):
        plan = P.build_plan([], [], [week(3)])
        self.assertEqual(plan["scope"], [])
        self.assertEqual(plan["cut_line"], [])

    def test_capacity_at_or_above_queue_size_leaves_no_cut_line(self):
        plan = P.build_plan([ready(1)], [], [week(5)])
        self.assertEqual(plan["cut_line"], [])

    def test_risk_items_pass_through_unfiltered(self):
        risk = [ready(9, "Blocked thing")]
        plan = P.build_plan([], risk, [])
        self.assertEqual(plan["risk"], risk)


class TestRenderIssueBody(unittest.TestCase):
    def test_assumed_capacity_says_so(self):
        plan = P.build_plan([ready(1)], [], [])
        body = P.render_issue_body(plan, {"role": "orchestrator", "run_url": "n/a"})
        self.assertIn("**Assumed** capacity", body)

    def test_measured_capacity_does_not_say_assumed(self):
        plan = P.build_plan([ready(1)], [], [week(2), week(2)])
        body = P.render_issue_body(plan, {"role": "orchestrator", "run_url": "n/a"})
        self.assertNotIn("**Assumed**", body)

    def test_cites_the_declaration_role(self):
        plan = P.build_plan([], [], [])
        body = P.render_issue_body(plan, {"role": "orchestrator", "run_url": "n/a"})
        self.assertIn("role: `orchestrator`", body)


class TestLoadCeremonyRole(unittest.TestCase):
    def test_reads_the_real_declaration_file(self):
        # The one true source: fails loudly if ceremonies/planning.yaml is
        # renamed, or its role field is removed, rather than a workflow
        # silently hardcoding a role that has drifted from it.
        role = P.load_ceremony_role()
        self.assertEqual(role, "orchestrator")


if __name__ == "__main__":
    unittest.main()
