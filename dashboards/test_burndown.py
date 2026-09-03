#!/usr/bin/env python3
"""Tests for the burndown and velocity dashboard.

`build_report` is pure — raw issue data in, report out — so the whole
computation is testable with fixtures at a fixed `now`. As with the
standup digest, every interesting case here is a window-boundary case
(an issue closed exactly at a day boundary, still open at the window
start, a closure landing on a weekly bucket edge), which is why `now`
is injected rather than read from the clock.

    python3 dashboards/test_burndown.py
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

spec = importlib.util.spec_from_file_location("dash_burndown", HERE / "burndown.py")
BD = importlib.util.module_from_spec(spec)
sys.modules["dash_burndown"] = BD
spec.loader.exec_module(BD)

NOW = datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc)


def ago(days: float) -> str:
    return (NOW - timedelta(days=days)).isoformat().replace("+00:00", "Z")


def story(number, created_days_ago, closed_days_ago=None, label="type:story"):
    return {
        "number": number,
        "createdAt": ago(created_days_ago),
        "closedAt": ago(closed_days_ago) if closed_days_ago is not None else None,
        "labels": [{"name": label}],
    }


def report(issues, window_days=14):
    return BD.build_report(issues, now=NOW, window_days=window_days)


class TestStoryFilter(unittest.TestCase):
    def test_only_type_story_issues_are_counted(self):
        r = report([
            story(1, created_days_ago=5),
            story(2, created_days_ago=5, label="type:bug"),
            story(3, created_days_ago=5, label="type:task"),
        ], window_days=5)
        self.assertEqual(r["story_count"], 1)
        self.assertEqual(r["burndown"][-1]["open"], 1)


class TestBurndown(unittest.TestCase):
    def test_issue_still_open_at_window_start_is_counted_throughout(self):
        r = report([story(1, created_days_ago=30)], window_days=10)
        self.assertTrue(all(p["open"] == 1 for p in r["burndown"]))

    def test_issue_created_after_a_boundary_is_not_counted_there(self):
        r = report([story(1, created_days_ago=3)], window_days=10)
        by_date = {p["date"]: p["open"] for p in r["burndown"]}
        oldest_boundary = min(by_date)
        newest_boundary = max(by_date)
        self.assertEqual(by_date[oldest_boundary], 0)
        self.assertEqual(by_date[newest_boundary], 1)

    def test_issue_closed_exactly_at_a_boundary_is_not_open_there(self):
        # The story is treated as no-longer-open once its closedAt reaches
        # the boundary, i.e. `created <= boundary < closed` is open.
        r = report([story(1, created_days_ago=10, closed_days_ago=5)], window_days=10)
        by_date = {p["date"]: p["open"] for p in r["burndown"]}
        boundary_at_close = (NOW - timedelta(days=5)).strftime("%Y-%m-%d")
        self.assertEqual(by_date[boundary_at_close], 0)

    def test_issue_still_open_the_day_before_it_closes(self):
        r = report([story(1, created_days_ago=10, closed_days_ago=5)], window_days=10)
        by_date = {p["date"]: p["open"] for p in r["burndown"]}
        day_before_close = (NOW - timedelta(days=6)).strftime("%Y-%m-%d")
        self.assertEqual(by_date[day_before_close], 1)

    def test_no_stories_is_reported_as_zero_not_omitted(self):
        r = report([], window_days=5)
        self.assertTrue(all(p["open"] == 0 for p in r["burndown"]))
        self.assertEqual(len(r["burndown"]), 6)  # window_days + 1 boundaries


class TestVelocity(unittest.TestCase):
    def test_this_weeks_bucket_counts_only_the_issue_closed_within_it(self):
        r = report([
            story(1, created_days_ago=20, closed_days_ago=14),  # two weeks ago
            story(2, created_days_ago=20, closed_days_ago=2),   # this week
        ], window_days=14)
        self.assertEqual(r["velocity"][-1]["closed"], 1)

    def test_a_closure_on_a_bucket_edge_lands_in_exactly_one_bucket(self):
        r = report([story(1, created_days_ago=20, closed_days_ago=7)], window_days=14)
        total_closed = sum(w["closed"] for w in r["velocity"])
        self.assertEqual(total_closed, 1)

    def test_bug_and_task_closures_are_excluded_from_velocity(self):
        r = report([
            story(1, created_days_ago=5, closed_days_ago=1, label="type:bug"),
            story(2, created_days_ago=5, closed_days_ago=1, label="type:task"),
        ], window_days=7)
        self.assertEqual(sum(w["closed"] for w in r["velocity"]), 0)

    def test_open_issue_does_not_count_toward_velocity(self):
        r = report([story(1, created_days_ago=5)], window_days=7)
        self.assertEqual(sum(w["closed"] for w in r["velocity"]), 0)


class TestRender(unittest.TestCase):
    def test_renders_self_contained_html(self):
        r = report([story(1, created_days_ago=5, closed_days_ago=1)], window_days=7)
        html = BD.render(r, {"repo": "a/b", "generated_at": "now"})
        self.assertIn("Burndown", html)
        self.assertIn("Velocity" if "Velocity" in html else "velocity", html)

    def test_empty_report_still_renders_a_page(self):
        html = BD.render(report([], window_days=5), {"repo": "a/b"})
        self.assertIn("Burndown", html)
        self.assertIn("<html", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
