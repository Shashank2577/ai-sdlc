#!/usr/bin/env python3
"""Tests for the decisions dashboard.

`waiting_rows` and `decided_rows` are pure — issues, PRs and pre-fetched
label events in, rows out — so every interesting case is a fixture at a
fixed `now`, same shape as `test_burndown.py` and `test_gate_check.py`.

Uses the real `policies/gates.yaml` via `gate_check.load_gate()`, not a
second copy of the rules — a test fixture that invents its own gate could
pass while this page disagrees with the actual policy.

    python3 dashboards/test_decisions.py
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

spec = importlib.util.spec_from_file_location("dash_decisions", HERE / "decisions.py")
D = importlib.util.module_from_spec(spec)
sys.modules["dash_decisions"] = D
spec.loader.exec_module(D)

NOW = datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)
GATE = D.G.load_gate()
SLA_HOURS = GATE["sla_hours"]


def ago(hours: float) -> str:
    return (NOW - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def issue(number, title="a story", body="", labels=(), state="OPEN",
         created_hours_ago=100):
    return {
        "number": number,
        "title": title,
        "body": body,
        "labels": [{"name": l} for l in labels],
        "url": f"https://example.invalid/issues/{number}",
        "state": state,
        "createdAt": ago(created_hours_ago),
    }


def label_event(event, label, actor, hours_ago):
    return {"event": event, "label": label, "actor": actor, "created_at": ago(hours_ago)}


class TestEmptyState(unittest.TestCase):
    def test_no_issues_or_prs_produces_no_waiting_rows(self):
        self.assertEqual(D.waiting_rows([], [], {}, GATE, SLA_HOURS, NOW), [])

    def test_no_candidates_produces_no_decided_rows(self):
        self.assertEqual(D.decided_rows([], {}, {}, GATE), [])

    def test_empty_report_still_renders_a_page(self):
        report = {"waiting": [], "decided": []}
        html = D.render(report, {"repo": "a/b", "generated_at": "now", "sla_hours": 24})
        self.assertIn("Nothing is waiting on a human", html)
        self.assertIn("No resolved holds yet", html)
        self.assertIn("<html", html)


class TestPastSLA(unittest.TestCase):
    def test_needs_human_item_older_than_sla_is_flagged(self):
        i = issue(1, labels=["needs-human"], created_hours_ago=SLA_HOURS + 10)
        events = {1: [label_event("labeled", "needs-human", "alice",
                                  SLA_HOURS + 6)]}
        rows = D.waiting_rows([i], [], events, GATE, SLA_HOURS, NOW)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["past_sla"])
        self.assertGreater(rows[0]["age_hours"], SLA_HOURS)
        self.assertEqual(rows[0]["sla_hours"], SLA_HOURS)

    def test_needs_human_item_within_sla_is_not_flagged(self):
        i = issue(2, labels=["needs-human"], created_hours_ago=2)
        events = {2: [label_event("labeled", "needs-human", "alice", 1)]}
        rows = D.waiting_rows([i], [], events, GATE, SLA_HOURS, NOW)
        self.assertFalse(rows[0]["past_sla"])

    def test_pull_request_rows_have_no_sla_verdict(self):
        pr = {"number": 5, "title": "a pr", "url": "https://example.invalid/pull/5",
             "isDraft": False, "reviewDecision": None, "createdAt": ago(500)}
        rows = D.waiting_rows([], [pr], {}, GATE, SLA_HOURS, NOW)
        self.assertIsNone(rows[0]["past_sla"])
        self.assertIsNone(rows[0]["sla_hours"])


class TestBotDecisionsExcluded(unittest.TestCase):
    def test_bot_applied_status_ready_is_not_logged_as_a_decision(self):
        i = issue(3, labels=["status:ready"], state="CLOSED")
        events = {3: [label_event("labeled", "status:ready",
                                  "github-actions[bot]", 5)]}
        self.assertEqual(D.decided_rows([i], events, {}, GATE), [])

    def test_human_applied_status_ready_is_logged(self):
        i = issue(4, labels=["status:ready"], state="CLOSED")
        events = {4: [label_event("labeled", "status:ready", "a-person", 5)]}
        rows = D.decided_rows([i], events, {}, GATE)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["by"], "a-person")

    def test_no_status_ready_event_on_record_is_not_logged(self):
        i = issue(6, labels=["status:ready"], state="CLOSED")
        self.assertEqual(D.decided_rows([i], {}, {}, GATE), [])


class TestUndeterminableReason(unittest.TestCase):
    def test_needs_human_with_no_matching_rule_reads_unknown(self):
        i = issue(7, title="a routine story", body="nothing critical here",
                  labels=["needs-human"])
        rows = D.waiting_rows([i], [], {7: []}, GATE, SLA_HOURS, NOW)
        self.assertEqual(rows[0]["why"], D.UNKNOWN)

    def test_unknown_reason_renders_as_the_word_unknown_not_omitted(self):
        i = issue(8, title="a routine story", body="nothing critical here",
                  labels=["needs-human"])
        report = {"waiting": D.waiting_rows([i], [], {8: []}, GATE, SLA_HOURS, NOW),
                  "decided": []}
        html = D.render(report, {"repo": "a/b", "generated_at": "now", "sla_hours": 24})
        self.assertIn("unknown", html)
        self.assertIn(f"#{i['number']}", html)

    def test_decided_row_with_no_matching_rule_reads_unknown_but_is_still_logged(self):
        i = issue(9, title="a routine story", body="nothing critical here",
                  labels=["status:ready"], state="CLOSED")
        events = {9: [label_event("labeled", "status:ready", "a-person", 5)]}
        rows = D.decided_rows([i], events, {}, GATE)
        self.assertEqual(rows[0]["why"], D.UNKNOWN)


class TestClassificationReusesTheGate(unittest.TestCase):
    def test_critical_status_needs_refinement_item_is_listed(self):
        i = issue(10, title="tidy a comment", labels=["status:needs-refinement",
                                                       "role:devops"])
        rows = D.waiting_rows([i], [], {10: []}, GATE, SLA_HOURS, NOW)
        self.assertEqual(len(rows), 1)
        self.assertIn("pipeline_role", [w["rule"] for w in rows[0]["why"]])

    def test_routine_status_needs_refinement_item_is_not_listed(self):
        i = issue(11, title="an ordinary story", body="Estimate: S",
                  labels=["status:needs-refinement"])
        rows = D.waiting_rows([i], [], {11: []}, GATE, SLA_HOURS, NOW)
        self.assertEqual(rows, [])

    def test_needs_human_and_critical_refinement_on_one_issue_is_not_duplicated(self):
        i = issue(12, title="tidy a comment",
                  labels=["needs-human", "status:needs-refinement", "role:devops"])
        rows = D.waiting_rows([i], [], {12: []}, GATE, SLA_HOURS, NOW)
        self.assertEqual(len(rows), 1)


class TestSorting(unittest.TestCase):
    def test_oldest_wait_is_first(self):
        old = issue(20, labels=["needs-human"])
        new = issue(21, labels=["needs-human"])
        events = {20: [label_event("labeled", "needs-human", "alice", 50)],
                 21: [label_event("labeled", "needs-human", "alice", 1)]}
        rows = D.waiting_rows([old, new], [], events, GATE, SLA_HOURS, NOW)
        self.assertEqual([r["number"] for r in rows], [20, 21])


if __name__ == "__main__":
    unittest.main(verbosity=2)
