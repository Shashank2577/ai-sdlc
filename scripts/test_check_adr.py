#!/usr/bin/env python3
"""Tests for the ADR validator.

Fixtures only — never the live adrs/ directory, so a future ADR cannot
break this suite by accident. The real directory gets its own single test
below, run through the same validate() function as everything else.

    python3 scripts/test_check_adr.py
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

spec = importlib.util.spec_from_file_location("check_adr", HERE / "check-adr.py")
C = importlib.util.module_from_spec(spec)
sys.modules["check_adr"] = C
spec.loader.exec_module(C)


def adr_text(
    number="0001",
    title="Do the thing",
    status="accepted",
    work_item="Shashank2577/foundry-program#1",
    requirement="REQ-001",
):
    return f"""# ADR-{number}: {title}

**Status:** {status}
**Work item:** {work_item}
**Requirement:** {requirement}

## Context

Some context.

## Decision

**Decided:** Option A
**Decided by:** a human
**Date:** 2026-09-02
"""


class AdrFixture:
    """A throwaway adrs/ directory: {filename: text}."""

    def __init__(self, files: dict[str, str]):
        self.tmp = Path(tempfile.mkdtemp())
        for name, text in files.items():
            (self.tmp / name).write_text(text)

    def __enter__(self) -> Path:
        return self.tmp

    def __exit__(self, *exc):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestHappyPath(unittest.TestCase):
    def test_a_well_formed_single_record_is_clean(self):
        with AdrFixture({"0001-do-the-thing.md": adr_text()}) as d:
            self.assertEqual(C.validate(d), [])

    def test_multiple_well_formed_records_are_clean(self):
        with AdrFixture(
            {
                "0001-do-the-thing.md": adr_text("0001", work_item="a/b#1"),
                "0002-do-another-thing.md": adr_text(
                    "0002", work_item="a/b#2", requirement="REQ-002"
                ),
            }
        ) as d:
            self.assertEqual(C.validate(d), [])

    def test_multi_issue_work_item_and_multi_req_are_accepted(self):
        text = adr_text(
            work_item="Shashank2577/foundry-program#75, #79",
            requirement="REQ-012, REQ-002",
        )
        with AdrFixture({"0001-do-the-thing.md": text}) as d:
            self.assertEqual(C.validate(d), [])

    def test_readme_is_ignored(self):
        with AdrFixture(
            {
                "0001-do-the-thing.md": adr_text(),
                "README.md": "# Architecture decision records\n",
            }
        ) as d:
            self.assertEqual(C.validate(d), [])

    def test_valid_supersedes_reference_is_accepted(self):
        with AdrFixture(
            {
                "0001-old-thing.md": adr_text("0001", status="superseded by ADR-0002"),
                "0002-new-thing.md": adr_text("0002", work_item="a/b#2"),
            }
        ) as d:
            self.assertEqual(C.validate(d), [])


class TestMissingRequiredField(unittest.TestCase):
    def test_missing_status_is_reported(self):
        text = adr_text().replace("**Status:** accepted\n", "")
        with AdrFixture({"0001-do-the-thing.md": text}) as d:
            violations = C.validate(d)
        self.assertTrue(any("missing **Status:**" in v for v in violations))

    def test_missing_work_item_is_reported(self):
        text = adr_text().replace(
            "**Work item:** Shashank2577/foundry-program#1\n", ""
        )
        with AdrFixture({"0001-do-the-thing.md": text}) as d:
            violations = C.validate(d)
        self.assertTrue(any("missing **Work item:**" in v for v in violations))

    def test_missing_requirement_is_reported(self):
        text = adr_text().replace("**Requirement:** REQ-001\n", "")
        with AdrFixture({"0001-do-the-thing.md": text}) as d:
            violations = C.validate(d)
        self.assertTrue(any("missing **Requirement:**" in v for v in violations))

    def test_missing_heading_is_reported(self):
        text = adr_text().replace("# ADR-0001: Do the thing\n", "")
        with AdrFixture({"0001-do-the-thing.md": text}) as d:
            violations = C.validate(d)
        self.assertTrue(any("missing `# ADR-NNNN" in v for v in violations))


class TestUnknownStatus(unittest.TestCase):
    def test_unrecognized_status_value_is_reported(self):
        with AdrFixture({"0001-do-the-thing.md": adr_text(status="in review")}) as d:
            violations = C.validate(d)
        self.assertTrue(
            any("'in review'" in v and "not one of" in v for v in violations)
        )

    def test_status_is_case_sensitive_to_the_template(self):
        with AdrFixture({"0001-do-the-thing.md": adr_text(status="Accepted")}) as d:
            violations = C.validate(d)
        self.assertTrue(any("not one of" in v for v in violations))


class TestDuplicateAdrNumber(unittest.TestCase):
    def test_two_files_claiming_the_same_number_is_reported(self):
        with AdrFixture(
            {
                "0001-first.md": adr_text("0001", title="First", work_item="a/b#1"),
                "0001-second.md": adr_text("0001", title="Second", work_item="a/b#2"),
            }
        ) as d:
            violations = C.validate(d)
        self.assertTrue(
            any("ADR-0001" in v and "more than one file" in v for v in violations)
        )


class TestDanglingSupersedes(unittest.TestCase):
    def test_supersedes_reference_to_nonexistent_adr_is_reported(self):
        with AdrFixture(
            {"0001-old-thing.md": adr_text(status="superseded by ADR-0099")}
        ) as d:
            violations = C.validate(d)
        self.assertTrue(
            any("ADR-0099" in v and "does not exist" in v for v in violations)
        )

    def test_supersedes_itself_is_reported(self):
        with AdrFixture(
            {"0001-old-thing.md": adr_text("0001", status="superseded by ADR-0001")}
        ) as d:
            violations = C.validate(d)
        self.assertTrue(any("superseded by itself" in v for v in violations))


class TestWorkItemShape(unittest.TestCase):
    def test_malformed_work_item_reference_is_reported(self):
        with AdrFixture(
            {"0001-do-the-thing.md": adr_text(work_item="issue 1")}
        ) as d:
            violations = C.validate(d)
        self.assertTrue(
            any("not a well-formed" in v and "owner" in v for v in violations)
        )

    def test_bare_issue_number_without_repo_is_reported(self):
        with AdrFixture({"0001-do-the-thing.md": adr_text(work_item="#1")}) as d:
            violations = C.validate(d)
        self.assertTrue(any("not a well-formed" in v for v in violations))


class TestRequirementShape(unittest.TestCase):
    def test_malformed_requirement_reference_is_reported(self):
        with AdrFixture(
            {"0001-do-the-thing.md": adr_text(requirement="performance")}
        ) as d:
            violations = C.validate(d)
        self.assertTrue(any("REQ-0XX" in v for v in violations))


class TestReportsEveryViolation(unittest.TestCase):
    def test_multiple_problems_in_one_file_are_all_reported(self):
        text = (
            adr_text(status="bogus", work_item="nope", requirement="nope")
            .replace("**Requirement:** nope\n", "")
        )
        with AdrFixture({"0001-do-the-thing.md": text}) as d:
            violations = C.validate(d)
        # status, work item, and the now-missing requirement — three
        # independent problems in one file, all surfaced in one run.
        self.assertGreaterEqual(len(violations), 3)

    def test_problems_across_multiple_files_are_all_reported(self):
        with AdrFixture(
            {
                "0001-first.md": adr_text("0001", status="bogus", work_item="a/b#1"),
                "0002-second.md": adr_text(
                    "0002", work_item="also bogus", requirement="REQ-002"
                ),
            }
        ) as d:
            violations = C.validate(d)
        self.assertGreaterEqual(len(violations), 2)


class TestLiveRecords(unittest.TestCase):
    def test_the_seven_backfilled_adrs_pass_clean(self):
        self.assertEqual(C.validate(REPO_ROOT / "adrs"), [])


class TestCLI(unittest.TestCase):
    def test_main_returns_zero_on_a_clean_directory(self):
        with AdrFixture({"0001-do-the-thing.md": adr_text()}) as d:
            self.assertEqual(C.main(["--dir", str(d)]), 0)

    def test_main_returns_nonzero_on_a_violation(self):
        with AdrFixture({"0001-do-the-thing.md": adr_text(status="bogus")}) as d:
            self.assertEqual(C.main(["--dir", str(d)]), 1)


if __name__ == "__main__":
    unittest.main()
