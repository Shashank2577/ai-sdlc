#!/usr/bin/env python3
"""Tests for the assignment loop.

`plan()` is a pure function of the board, so the whole selection —
eligibility, WIP arithmetic, per-role caps, ordering — is testable without
a repository. Which is the point: two runs against the same board must
make the same decisions, and that is only checkable if the decision is a
function.

    python3 scripts/test_assign.py
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("assign", HERE / "assign.py")
A = importlib.util.module_from_spec(spec)
sys.modules["assign"] = A
spec.loader.exec_module(A)

POLICY = {
    "wip": {"limit": 3, "counts": ["status:in-progress"],
            "per_role": {"developer": 3, "qa": 2}},
    "routing": {"prefix": "role:", "supported": ["developer", "qa"], "default": None},
    "eligibility": {
        "require_labels": ["status:ready"],
        "exclude_labels": ["needs-human", "status:blocked", "qa:rejected"],
        "require_open": True,
    },
}


def issue(number, *labels, state="OPEN", title=None):
    return {"number": number, "title": title or f"item {number}", "state": state,
            "url": f"https://example/{number}", "labels": [{"name": n} for n in labels]}


def ready(number, role="developer", *extra):
    return issue(number, "status:ready", f"role:{role}", *extra)


class TestEligibility(unittest.TestCase):
    def eligible(self, iss):
        return A.ineligible_reason(iss, POLICY) is None

    def test_ready_with_a_role_is_eligible(self):
        self.assertTrue(self.eligible(ready(1)))

    def test_not_ready_is_not_eligible(self):
        self.assertEqual(A.ineligible_reason(issue(1, "role:developer"), POLICY),
                         "missing status:ready")

    def test_closed_is_not_eligible(self):
        self.assertEqual(
            A.ineligible_reason(ready(1) | {"state": "CLOSED"}, POLICY), "not open")

    def test_needs_human_blocks(self):
        self.assertIn("needs-human", A.ineligible_reason(ready(1, "developer",
                                                               "needs-human"), POLICY))

    def test_blocked_blocks(self):
        self.assertIn("status:blocked",
                      A.ineligible_reason(ready(1, "developer", "status:blocked"), POLICY))

    def test_qa_rejected_blocks(self):
        # Rejected work goes back through its author, not through fresh
        # assignment.
        self.assertIn("qa:rejected",
                      A.ineligible_reason(ready(1, "developer", "qa:rejected"), POLICY))

    def test_no_role_label_is_never_guessed(self):
        reason = A.ineligible_reason(issue(1, "status:ready"), POLICY)
        self.assertIn("no `role:*` label", reason)
        self.assertIn("refinement", reason)

    def test_two_role_labels_is_a_contradiction_not_a_choice(self):
        iss = issue(1, "status:ready", "role:developer", "role:qa")
        self.assertIn("several role labels", A.ineligible_reason(iss, POLICY))

    def test_an_unsupported_role_is_named_with_what_is_supported(self):
        reason = A.ineligible_reason(issue(1, "status:ready", "role:architect"), POLICY)
        self.assertIn("architect", reason)
        self.assertIn("developer, qa", reason)


class TestWipLimit(unittest.TestCase):
    def test_dispatches_up_to_the_limit(self):
        p = A.plan([ready(n) for n in (1, 2, 3, 4, 5)], POLICY)
        self.assertEqual([d["number"] for d in p["dispatch"]], [1, 2, 3])
        self.assertEqual([d["number"] for d in p["deferred"]], [4, 5])

    def test_in_flight_work_consumes_slots(self):
        board = [issue(1, "status:in-progress", "role:developer"),
                 issue(2, "status:in-progress", "role:developer"),
                 ready(3), ready(4)]
        p = A.plan(board, POLICY)
        self.assertEqual(p["in_flight"], 2)
        self.assertEqual(p["slots"], 1)
        self.assertEqual([d["number"] for d in p["dispatch"]], [3])

    def test_a_full_board_dispatches_nothing(self):
        board = [issue(n, "status:in-progress", "role:developer") for n in (1, 2, 3)]
        board += [ready(4)]
        p = A.plan(board, POLICY)
        self.assertEqual(p["dispatch"], [])
        self.assertEqual(p["slots"], 0)
        self.assertIn("WIP limit 3", p["deferred"][0]["reason"])

    def test_over_the_limit_does_not_produce_negative_slots(self):
        board = [issue(n, "status:in-progress", "role:developer") for n in range(1, 6)]
        board += [ready(9)]
        p = A.plan(board, POLICY)
        self.assertEqual(p["slots"], 0)
        self.assertEqual(p["dispatch"], [])

    def test_closed_in_progress_items_do_not_consume_slots(self):
        board = [issue(1, "status:in-progress", "role:developer", state="CLOSED"),
                 ready(2)]
        p = A.plan(board, POLICY)
        self.assertEqual(p["in_flight"], 0)
        self.assertEqual([d["number"] for d in p["dispatch"]], [2])


class TestPerRoleCap(unittest.TestCase):
    def test_a_role_cap_defers_under_the_global_limit(self):
        p = A.plan([ready(1, "qa"), ready(2, "qa"), ready(3, "qa")], POLICY)
        self.assertEqual([d["number"] for d in p["dispatch"]], [1, 2])
        self.assertIn("per-role cap for `qa` is 2", p["deferred"][0]["reason"])

    def test_in_flight_work_counts_toward_the_role_cap(self):
        board = [issue(1, "status:in-progress", "role:qa"), ready(2, "qa"), ready(3, "qa")]
        p = A.plan(board, POLICY)
        self.assertEqual([d["number"] for d in p["dispatch"]], [2])
        self.assertIn("per-role cap", p["deferred"][0]["reason"])

    def test_a_capped_role_does_not_block_another_role(self):
        board = [issue(1, "status:in-progress", "role:qa"),
                 ready(2, "qa"), ready(3, "qa"), ready(4, "developer")]
        p = A.plan(board, POLICY)
        self.assertEqual([(d["number"], d["role"]) for d in p["dispatch"]],
                         [(2, "qa"), (4, "developer")])

    def test_a_role_without_a_cap_is_bounded_only_by_the_global_limit(self):
        policy = {**POLICY, "wip": {**POLICY["wip"], "per_role": {}}}
        p = A.plan([ready(n, "qa") for n in (1, 2, 3, 4)], policy)
        self.assertEqual(len(p["dispatch"]), 3)


class TestOrdering(unittest.TestCase):
    def test_lowest_number_first(self):
        p = A.plan([ready(9), ready(2), ready(5)], POLICY)
        self.assertEqual([d["number"] for d in p["dispatch"]], [2, 5, 9])

    def test_work_already_in_flight_as_a_pr_goes_first(self):
        # Finishing beats starting.
        p = A.plan([ready(2), ready(5), ready(9)], POLICY, with_open_pr={9})
        self.assertEqual([d["number"] for d in p["dispatch"]], [9, 2, 5])

    def test_the_same_board_always_gives_the_same_plan(self):
        board = [ready(4), ready(1), ready(7, "qa"), issue(3, "status:ready")]
        first = A.plan(board, POLICY)
        second = A.plan(list(reversed(board)), POLICY)
        self.assertEqual(first, second)


class TestQuietLoop(unittest.TestCase):
    def test_an_empty_board_produces_an_empty_plan(self):
        p = A.plan([], POLICY)
        self.assertEqual(p["dispatch"], [])
        self.assertEqual(p["skipped"], [])
        self.assertEqual(p["eligible_total"], 0)

    def test_nothing_eligible_produces_no_dispatch_but_explains_itself(self):
        p = A.plan([issue(1, "status:needs-refinement"), issue(2, "status:ready")],
                   POLICY)
        self.assertEqual(p["dispatch"], [])
        self.assertEqual({s["number"] for s in p["skipped"]}, {1, 2})
        self.assertIn("missing status:ready", p["skipped"][0]["reason"])

    def test_the_report_names_every_decision(self):
        p = A.plan([ready(1), issue(2, "status:ready"),
                    issue(3, "status:in-progress", "role:developer")], POLICY)
        report = A.render_plan(p, "policy.yaml")
        self.assertIn("dispatch #1", report)
        self.assertIn("skip     #2", report)
        self.assertIn("1/3 in flight", report)


class TestPolicyLoading(unittest.TestCase):
    def test_the_committed_policy_loads_and_is_bounded(self):
        policy, source = A.load_policy()
        self.assertIn("orchestrator/policy.yaml", source)
        self.assertGreaterEqual(policy["wip"]["limit"], 1)
        self.assertLessEqual(policy["wip"]["limit"], 10,
                             "a WIP limit above 10 is a review queue, not a limit")
        self.assertIn("developer", policy["routing"]["supported"])

    def test_a_missing_policy_falls_back_to_something_conservative(self):
        policy, source = A.load_policy(Path("/nonexistent/policy.yaml"))
        self.assertIn("fallback", source)
        self.assertEqual(policy["wip"]["limit"], 1,
                         "a broken policy read must not become an unbounded loop")

    def test_the_committed_policy_drives_the_planner(self):
        policy, _ = A.load_policy()
        p = A.plan([ready(n) for n in range(1, 9)], policy)
        self.assertEqual(len(p["dispatch"]), policy["wip"]["limit"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
