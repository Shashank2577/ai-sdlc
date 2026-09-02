#!/usr/bin/env python3
"""Tests for the label -> project-board mapping.

`desired_fields` and `diff` are pure, so the whole mapping is testable
without a project. That matters here more than usual: this code writes to
a surface humans read as the truth, and a wrong mapping is invisible —
the board just quietly says the wrong thing.

    python3 scripts/test_sync_project.py
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("sync_project", HERE / "sync-project.py")
S = importlib.util.module_from_spec(spec)
sys.modules["sync_project"] = S
spec.loader.exec_module(S)


def issue(*labels, state="OPEN", body="", number=1):
    return {"number": number, "state": state, "body": body,
            "labels": [{"name": n} for n in labels]}


class TestStatusMapping(unittest.TestCase):
    def test_each_status_label_maps_to_its_column(self):
        for label, column in S.STATUS_BY_LABEL:
            with self.subTest(label=label):
                self.assertEqual(desired := S.desired_fields(issue(label))["Status"], column,
                                 f"{label} -> {desired}")

    def test_no_status_label_is_todo(self):
        self.assertEqual(S.desired_fields(issue("type:story"))["Status"], "Todo")

    def test_closed_outranks_any_label(self):
        # An item can carry a stale status label. Closed is a fact.
        self.assertEqual(
            S.desired_fields(issue("status:in-review", state="CLOSED"))["Status"], "Done")

    def test_blocked_wins_over_other_status_labels(self):
        # Two status labels is a bug, but it must resolve the same way every
        # run or the board flickers between syncs.
        both = issue("status:ready", "status:blocked")
        self.assertEqual(S.desired_fields(both)["Status"], "Blocked")
        self.assertEqual(S.desired_fields(both)["Status"],
                         S.desired_fields(issue("status:blocked", "status:ready"))["Status"])


class TestRoleAndVerdict(unittest.TestCase):
    def test_role_label_maps_to_the_role_field(self):
        self.assertEqual(S.desired_fields(issue("role:developer"))["Role"], "Developer")
        self.assertEqual(S.desired_fields(issue("role:qa"))["Role"], "QA")

    def test_no_role_label_leaves_the_field_alone(self):
        # Absent, not blanked: the board should not fight a human who set it.
        self.assertNotIn("Role", S.desired_fields(issue("status:ready")))

    def test_qa_defaults_to_pending(self):
        self.assertEqual(S.desired_fields(issue())["QA-Verdict"], "Pending")

    def test_qa_labels_map_to_verdicts(self):
        self.assertEqual(S.desired_fields(issue("qa:approved"))["QA-Verdict"], "Approved")
        self.assertEqual(S.desired_fields(issue("qa:rejected"))["QA-Verdict"], "Rejected")

    def test_rejected_wins_when_both_verdicts_are_present(self):
        # A story carrying both is broken; the safe reading is the veto.
        self.assertEqual(
            S.desired_fields(issue("qa:approved", "qa:rejected"))["QA-Verdict"], "Rejected")


class TestRequirementExtraction(unittest.TestCase):
    def test_reads_the_convention_marker(self):
        body = "**As the** org **I want** x **so that** y. → **REQ-002, REQ-003**"
        self.assertEqual(S.desired_fields(issue(body=body))["Requirement-ID"],
                         "REQ-002, REQ-003")

    def test_the_marker_is_authoritative_over_incidental_mentions(self):
        body = ("Story. → **REQ-002**\n\nAcceptance criteria:\n"
                "Given REQ-009 is not in scope here, it must not be linked.")
        self.assertEqual(S.desired_fields(issue(body=body))["Requirement-ID"], "REQ-002")

    def test_falls_back_to_the_whole_body_without_a_marker(self):
        body = "No marker, but mentions REQ-005 and REQ-001."
        self.assertEqual(S.desired_fields(issue(body=body))["Requirement-ID"],
                         "REQ-001, REQ-005")

    def test_ids_are_sorted_and_deduplicated(self):
        body = "→ **REQ-009, REQ-002, REQ-009**"
        self.assertEqual(S.desired_fields(issue(body=body))["Requirement-ID"],
                         "REQ-002, REQ-009")

    def test_no_requirements_leaves_the_field_alone(self):
        self.assertNotIn("Requirement-ID", S.desired_fields(issue(body="nothing here")))


class TestDiff(unittest.TestCase):
    def test_a_correct_board_produces_no_writes(self):
        # The sync runs on a schedule; a no-op run must write nothing, or
        # every run churns the board's own activity feed.
        desired = {"Status": "Done", "QA-Verdict": "Pending"}
        self.assertEqual(S.diff({"Status": "Done", "QA-Verdict": "Pending"}, desired), {})

    def test_only_the_differing_fields_are_written(self):
        current = {"Status": "In Review", "QA-Verdict": "Pending", "Role": "Developer"}
        desired = {"Status": "Done", "QA-Verdict": "Pending"}
        self.assertEqual(S.diff(current, desired), {"Status": "Done"})

    def test_an_unset_field_counts_as_differing(self):
        self.assertEqual(S.diff({}, {"Role": "QA"}), {"Role": "QA"})


class TestAgainstThisRepo(unittest.TestCase):
    def test_every_status_label_in_conventions_has_a_column(self):
        conventions = (HERE.parent / ".github").parent
        labels = {l for l, _ in S.STATUS_BY_LABEL}
        expected = {"status:needs-refinement", "status:ready", "status:in-progress",
                    "status:in-review", "status:blocked"}
        self.assertEqual(labels, expected,
                         "the board mapping and the label state machine have diverged")

    def test_every_role_pack_in_the_repo_has_a_role_label_mapping(self):
        packs = sorted(p.name for p in (HERE.parent / "role-packs").iterdir()
                       if (p / "pack.yaml").is_file())
        for role in packs:
            with self.subTest(role=role):
                self.assertIn(f"role:{role}", S.ROLE_BY_LABEL,
                              f"role pack `{role}` has no board mapping")


if __name__ == "__main__":
    unittest.main(verbosity=2)
