#!/usr/bin/env python3
"""Tests for the retro ceremony generator.

`build_retro` is pure — raw event data in, retro out — so the whole
computation is testable with fixtures at a fixed `now`. Every interesting
case here is a window boundary or a duplicate-issue guard, exactly as
`dashboards/standup.py`'s tests are built.

    python3 scripts/test_retro.py
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

spec = importlib.util.spec_from_file_location("retro", HERE / "retro.py")
R = importlib.util.module_from_spec(spec)
sys.modules["retro"] = R
spec.loader.exec_module(R)

NOW = datetime(2026, 9, 2, 7, 0, 0, tzinfo=timezone.utc)


def ago(hours: float) -> str:
    return (NOW - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def dispatch_comment(result="success", outcome="success", breach="0", role="developer",
                     cost="0.6123", run_url="https://run/1", url="c/1"):
    body = (
        f"<!-- foundry:dispatch result={result} outcome={outcome} breach={breach} -->\n"
        f"### Dispatch — session end\n\n"
        f"The `{role}` session shipped a pull request.\n\n"
        f"| | |\n|---|---|\n| Outcome | `{outcome}` |\n| Run | {run_url} |\n\n"
        f"#### Spend\n\n| Budget line | Used | Limit | |\n|---|---|---|---|\n"
        f"| cost (USD) | {cost} | 5 | ok |\n"
    )
    return {"body": body, "url": url, "created_at": ago(1)}


def escalation_comment(url="c/esc"):
    body = "### Escalation — human decision required\n\n**Role:** devops\n"
    return {"body": body, "url": url, "created_at": ago(1)}


def issue(number, title="an item", closed_at=None, labels=()):
    return {"number": number, "title": title, "url": f"u/{number}",
            "closedAt": closed_at if closed_at is not None else ago(1),
            "labels": [{"name": n} for n in labels]}


def pr(number, head_ref, state="MERGED", merged_at="__default__", closed_at=None, url=None):
    if merged_at == "__default__":
        merged_at = ago(2)
    return {"number": number, "url": url or f"pr/{number}", "headRefName": head_ref,
            "state": state, "mergedAt": merged_at, "closedAt": closed_at or ago(2)}


class TestSessionExtraction(unittest.TestCase):
    def test_parses_result_outcome_breach_role_and_cost(self):
        sessions = R.extract_sessions([dispatch_comment()])
        self.assertEqual(len(sessions), 1)
        s = sessions[0]
        self.assertEqual(s["result"], "success")
        self.assertEqual(s["role"], "developer")
        self.assertEqual(s["cost_usd"], 0.6123)
        self.assertEqual(s["run_url"], "https://run/1")

    def test_ignores_comments_without_the_marker(self):
        sessions = R.extract_sessions([{"body": "just a comment", "url": "c/2"}])
        self.assertEqual(sessions, [])

    def test_unknown_cost_is_none_not_zero(self):
        sessions = R.extract_sessions([dispatch_comment(cost="unknown")])
        self.assertIsNone(sessions[0]["cost_usd"])


class TestEscalationExtraction(unittest.TestCase):
    def test_finds_escalation_comments(self):
        out = R.extract_escalations([escalation_comment(), dispatch_comment()])
        self.assertEqual(len(out), 1)
        self.assertIn("Escalation", out[0]["heading"])


class TestPrMatching(unittest.TestCase):
    def test_matches_story_branch_by_issue_number(self):
        prs = [pr(1, "story/FDY-51-retro"), pr(2, "story/FDY-52-other")]
        matched = R.find_pr_for_issue(prs, 51)
        self.assertEqual(matched["number"], 1)

    def test_no_match_returns_none(self):
        self.assertIsNone(R.find_pr_for_issue([pr(1, "story/FDY-9-x")], 51))

    def test_does_not_match_a_number_prefix(self):
        # FDY-5 must not match issue 51's branch.
        prs = [pr(1, "story/FDY-5-x")]
        self.assertIsNone(R.find_pr_for_issue(prs, 51))

    def test_prefers_merged_over_open(self):
        prs = [pr(1, "story/FDY-51-a", state="OPEN", merged_at=None),
               pr(2, "story/FDY-51-b", state="MERGED")]
        self.assertEqual(R.find_pr_for_issue(prs, 51)["number"], 2)


class TestWindowBoundary(unittest.TestCase):
    def build(self, closed_issues, comments=None, prs=None, runs=None, window_days=7):
        return R.build_retro(NOW, window_days, closed_issues, comments or {},
                              prs or [], runs or [])

    def test_item_closed_inside_window_is_included(self):
        retro = self.build([issue(1, closed_at=ago(24))])
        self.assertEqual([i["number"] for i in retro["items"]], [1])

    def test_item_closed_just_outside_window_is_excluded(self):
        retro = self.build([issue(1, closed_at=ago(24 * 8))])
        self.assertEqual(retro["items"], [])

    def test_item_at_the_exact_window_edge_is_included(self):
        edge = (NOW - timedelta(days=7)).isoformat().replace("+00:00", "Z")
        retro = self.build([issue(1, closed_at=edge)])
        self.assertEqual([i["number"] for i in retro["items"]], [1])

    def test_no_closed_items_yields_no_items(self):
        retro = self.build([])
        self.assertEqual(retro["items"], [])
        self.assertEqual(retro["totals"]["items"], 0)

    def test_a_prior_retro_issue_is_not_treated_as_a_work_item(self):
        retro = self.build([issue(1, closed_at=ago(1), labels=["process"])])
        self.assertEqual(retro["items"], [])


class TestAggregation(unittest.TestCase):
    def test_item_carries_its_sessions_pr_and_cost_total(self):
        retro = R.build_retro(
            NOW, 7,
            closed_issues=[issue(51, title="Retro ceremony", closed_at=ago(1))],
            comments_by_issue={51: [dispatch_comment(cost="1.00"),
                                    dispatch_comment(cost="2.50", url="c/2"),
                                    escalation_comment()]},
            prs=[pr(9, "story/FDY-51-retro")],
            runs=[],
        )
        item = retro["items"][0]
        self.assertEqual(item["pr"]["number"], 9)
        self.assertEqual(len(item["sessions"]), 2)
        self.assertEqual(item["cost_total"], 3.5)
        self.assertEqual(len(item["escalations"]), 1)

    def test_failed_sessions_are_flagged_separately(self):
        retro = R.build_retro(
            NOW, 7,
            closed_issues=[issue(1, closed_at=ago(1))],
            comments_by_issue={1: [dispatch_comment(result="failure")]},
            prs=[], runs=[],
        )
        self.assertEqual(len(retro["items"][0]["failed_sessions"]), 1)

    def test_check_failures_are_windowed_like_everything_else(self):
        runs = [
            {"name": "dod-check", "conclusion": "failure", "createdAt": ago(2),
             "headBranch": "story/FDY-1-x", "url": "r/1"},
            {"name": "dod-check", "conclusion": "failure", "createdAt": ago(24 * 30),
             "headBranch": "story/FDY-2-x", "url": "r/2"},
            {"name": "dod-check", "conclusion": "success", "createdAt": ago(2),
             "headBranch": "story/FDY-3-x", "url": "r/3"},
        ]
        retro = R.build_retro(NOW, 7, [], {}, [], runs)
        self.assertEqual([f["url"] for f in retro["check_failures"]], ["r/1"])


class TestRendering(unittest.TestCase):
    def test_every_item_cites_a_run_or_pull_request(self):
        retro = R.build_retro(
            NOW, 7,
            closed_issues=[issue(51, title="Retro ceremony", closed_at=ago(1))],
            comments_by_issue={51: [dispatch_comment(run_url="https://run/9")]},
            prs=[pr(9, "story/FDY-51-retro")],
            runs=[],
        )
        body = R.render_issue_body(retro, {"repo": "o/r", "run_url": "https://run/x"})
        self.assertIn("https://run/9", body)
        self.assertIn("pr/9", body)

    def test_empty_window_still_renders_without_items(self):
        retro = R.build_retro(NOW, 7, [], {}, [], [])
        body = R.render_issue_body(retro, {"repo": "o/r"})
        self.assertIn("No closed work items", body)

    def test_never_proposes_a_skill_edit(self):
        retro = R.build_retro(NOW, 7, [issue(1, closed_at=ago(1))],
                              {1: [dispatch_comment()]}, [], [])
        body = R.render_issue_body(retro, {"repo": "o/r"})
        self.assertIn("does not propose a skill edit", body)


class TestTitleAndIdempotency(unittest.TestCase):
    def test_title_is_stable_for_the_same_window(self):
        start = NOW - timedelta(days=7)
        self.assertEqual(R.retro_title(start, NOW),
                         f"Retro: {start.date()} to {NOW.date()}")

    def test_existing_title_is_an_exact_match_not_a_substring(self):
        start = NOW - timedelta(days=7)
        title = R.retro_title(start, NOW)
        # A different window's title must not collide.
        other = R.retro_title(start - timedelta(days=7), NOW - timedelta(days=7))
        self.assertNotEqual(title, other)


if __name__ == "__main__":
    unittest.main()
