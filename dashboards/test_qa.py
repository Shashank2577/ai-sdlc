#!/usr/bin/env python3
"""Tests for the QA verdict dashboard.

`build_matrix` is pure — issue records in, matrix out — so every case here
is a fixed fixture rather than a live tracker query, following the same
approach `test_standup.py` uses (see that file's own docstring).

    python3 dashboards/test_qa.py
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

spec = importlib.util.spec_from_file_location("dash_qa", HERE / "qa.py")
Q = importlib.util.module_from_spec(spec)
sys.modules["dash_qa"] = Q
spec.loader.exec_module(Q)


def issue(number, *labels, reqs="REQ-009", title="an item", state="OPEN", no_marker=False):
    body = "some acceptance criteria mentioning REQ-999 in passing" if no_marker \
        else f"**As the** x **I want** y **so that** z → **{reqs}**"
    return {"number": number, "title": title, "state": state, "body": body,
            "labels": [{"name": n} for n in labels]}


class TestReqParsing(unittest.TestCase):
    def test_marker_reqs_are_extracted(self):
        self.assertEqual(Q.issue_requirements("→ **REQ-009**"), ["REQ-009"])

    def test_multiple_reqs_in_one_marker(self):
        self.assertEqual(Q.issue_requirements("→ **REQ-002, REQ-003**"),
                         ["REQ-002", "REQ-003"])

    def test_no_marker_yields_no_requirements(self):
        self.assertEqual(Q.issue_requirements("REQ-999 mentioned in the body only"), [])

    def test_empty_body_does_not_crash(self):
        self.assertEqual(Q.issue_requirements(None), [])


class TestVerdict(unittest.TestCase):
    def test_qa_approved_label(self):
        self.assertEqual(Q.verdict(issue(1, "qa:approved")), Q.APPROVED)

    def test_qa_rejected_label(self):
        self.assertEqual(Q.verdict(issue(1, "qa:rejected")), Q.REJECTED)

    def test_neither_label_is_pending(self):
        self.assertEqual(Q.verdict(issue(1, "type:story")), Q.PENDING)

    def test_rejected_outranks_approved_if_both_present(self):
        self.assertEqual(Q.verdict(issue(1, "qa:approved", "qa:rejected")), Q.REJECTED)


class TestBuildMatrix(unittest.TestCase):
    def test_approved_issue_lands_under_its_req_as_approved(self):
        m = Q.build_matrix([issue(1, "qa:approved", reqs="REQ-009")])
        self.assertEqual(m["REQ-009"][0]["number"], 1)
        self.assertEqual(m["REQ-009"][0]["verdict"], Q.APPROVED)

    def test_rejected_issue_is_never_silently_omitted(self):
        m = Q.build_matrix([issue(2, "qa:rejected", reqs="REQ-009")])
        self.assertIn("REQ-009", m)
        self.assertEqual(m["REQ-009"][0]["verdict"], Q.REJECTED)

    def test_issue_with_neither_label_lands_as_pending(self):
        m = Q.build_matrix([issue(3, reqs="REQ-009")])
        self.assertEqual(m["REQ-009"][0]["verdict"], Q.PENDING)

    def test_issue_without_req_marker_is_excluded_not_crashed(self):
        m = Q.build_matrix([issue(4, "qa:approved", no_marker=True)])
        self.assertEqual(m, {})

    def test_issue_serving_multiple_reqs_appears_under_each(self):
        m = Q.build_matrix([issue(5, "qa:approved", reqs="REQ-002, REQ-003")])
        self.assertEqual(m["REQ-002"][0]["number"], 5)
        self.assertEqual(m["REQ-003"][0]["number"], 5)

    def test_entries_within_a_req_are_ordered_by_number(self):
        m = Q.build_matrix([issue(9, reqs="REQ-009"), issue(2, reqs="REQ-009")])
        self.assertEqual([e["number"] for e in m["REQ-009"]], [2, 9])

    def test_mixed_batch_keeps_every_issue_present(self):
        m = Q.build_matrix([
            issue(1, "qa:approved", reqs="REQ-009"),
            issue(2, "qa:rejected", reqs="REQ-009"),
            issue(3, reqs="REQ-009"),
        ])
        self.assertEqual(len(m["REQ-009"]), 3)
        verdicts = {e["number"]: e["verdict"] for e in m["REQ-009"]}
        self.assertEqual(verdicts, {1: Q.APPROVED, 2: Q.REJECTED, 3: Q.PENDING})


class TestReqStatus(unittest.TestCase):
    def test_all_approved_is_approved(self):
        entries = [{"verdict": Q.APPROVED}, {"verdict": Q.APPROVED}]
        self.assertEqual(Q.req_status(entries), Q.APPROVED)

    def test_any_rejected_fails_the_row(self):
        entries = [{"verdict": Q.APPROVED}, {"verdict": Q.REJECTED}]
        self.assertEqual(Q.req_status(entries), Q.REJECTED)

    def test_pending_beats_approved_when_no_rejection(self):
        entries = [{"verdict": Q.APPROVED}, {"verdict": Q.PENDING}]
        self.assertEqual(Q.req_status(entries), Q.PENDING)


class TestRender(unittest.TestCase):
    def test_renders_self_contained_html_and_escapes_titles(self):
        m = Q.build_matrix([issue(1, "qa:rejected", reqs="REQ-009",
                                  title="fix <script>alert(1)</script>")])
        html = Q.render_html(m, {"repo": "a/b", "repo_url": "https://github.com/a/b",
                                 "generated_at": "now"})
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>alert", html)
        self.assertIn("REQ-009", html)
        self.assertIn("rejected", html)

    def test_empty_matrix_still_renders_a_page(self):
        html = Q.render_html({}, {"repo": "a/b", "repo_url": "https://github.com/a/b"})
        self.assertIn("No issue carries a REQ marker", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
