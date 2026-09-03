#!/usr/bin/env python3
"""Tests for the ADR dashboard.

Parsing, linking and rendering are pure functions over strings, so every
case here is a fixed fixture rather than a real `adrs/` directory —
following the same approach test_qa.py and test_build.py use.

    python3 dashboards/test_adr.py
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent

spec = importlib.util.spec_from_file_location("dash_adr", HERE / "adr.py")
A = importlib.util.module_from_spec(spec)
sys.modules["dash_adr"] = A
spec.loader.exec_module(A)


def adr_text(id_="0001", title="A decision", status="accepted",
              work_item="acme/widgets#1", requirement="REQ-001",
              decided_by="human", date="2026-09-01",
              extra_sections=True) -> str:
    body = f"""# ADR-{id_}: {title}

**Status:** {status}
**Work item:** {work_item}
**Requirement:** {requirement}

## Context

Some forcing context.

## Options considered

### Option A: do it

- **Cost:** low
- **Consequence:** it happens

## Recommendation

Recommend A.

## Decision

**Decided:** Option A
**Decided by:** {decided_by}
**Date:** {date}

Chosen because it was cheapest.

## Consequences

- ongoing cost one
- ongoing cost two
"""
    return body if extra_sections else body


class TestParseAdr(unittest.TestCase):
    def test_well_formed_record_parses_every_field(self):
        r = A.parse_adr("0001-a-decision.md", adr_text(), known_reqs={"REQ-001"})
        self.assertIsNone(r.error)
        self.assertEqual(r.id, "0001")
        self.assertEqual(r.title, "A decision")
        self.assertEqual(r.status, "accepted")
        self.assertEqual(r.work_item, "acme/widgets#1")
        self.assertEqual(r.requirements, ["REQ-001"])
        self.assertEqual(r.unknown_requirements, [])
        self.assertEqual(r.decided_by, "human")
        self.assertEqual(r.date, "2026-09-01")
        names = [name for name, _ in r.sections]
        self.assertEqual(names, ["Context", "Options considered", "Recommendation",
                                 "Decision", "Consequences"])

    def test_missing_heading_is_a_parse_error_not_a_crash(self):
        r = A.parse_adr("weird.md", "no heading here\n\n**Status:** accepted",
                        known_reqs=set())
        self.assertIsNotNone(r.error)
        self.assertEqual(r.id, "weird.md")

    def test_missing_status_is_a_parse_error(self):
        text = "# ADR-0002: Something\n\n## Context\n\nno status field\n"
        r = A.parse_adr("0002-something.md", text, known_reqs=set())
        self.assertIsNotNone(r.error)
        self.assertEqual(r.id, "0002")
        self.assertEqual(r.title, "Something")

    def test_superseded_status_is_parsed_with_target_id(self):
        text = adr_text(status="superseded by ADR-0009")
        r = A.parse_adr("0001-a.md", text, known_reqs={"REQ-001"})
        self.assertEqual(r.status, "superseded")
        self.assertEqual(r.superseded_by, "0009")

    def test_req_not_in_index_is_flagged_unknown(self):
        r = A.parse_adr("0001-a.md", adr_text(requirement="REQ-999"), known_reqs={"REQ-001"})
        self.assertEqual(r.requirements, ["REQ-999"])
        self.assertEqual(r.unknown_requirements, ["REQ-999"])

    def test_multiple_requirements_split_and_sorted(self):
        r = A.parse_adr("0001-a.md", adr_text(requirement="REQ-003, REQ-001"),
                        known_reqs={"REQ-001", "REQ-003"})
        self.assertEqual(r.requirements, ["REQ-001", "REQ-003"])


class TestLinkSupersession(unittest.TestCase):
    def test_superseding_record_gets_backlink(self):
        old = A.parse_adr("0001-old.md", adr_text(id_="0001", status="superseded by ADR-0002"),
                          known_reqs={"REQ-001"})
        new = A.parse_adr("0002-new.md", adr_text(id_="0002"), known_reqs={"REQ-001"})
        A.link_supersession([old, new])
        self.assertEqual(old.superseded_by, "0002")
        self.assertEqual(new.supersedes, ["0001"])

    def test_chain_of_three_links_each_hop(self):
        a = A.parse_adr("0001-a.md", adr_text(id_="0001", status="superseded by ADR-0002"),
                        known_reqs={"REQ-001"})
        b = A.parse_adr("0002-b.md", adr_text(id_="0002", status="superseded by ADR-0003"),
                        known_reqs={"REQ-001"})
        c = A.parse_adr("0003-c.md", adr_text(id_="0003"), known_reqs={"REQ-001"})
        A.link_supersession([a, b, c])
        self.assertEqual(a.superseded_by, "0002")
        self.assertEqual(b.supersedes, ["0001"])
        self.assertEqual(b.superseded_by, "0003")
        self.assertEqual(c.supersedes, ["0002"])

    def test_dangling_superseded_by_does_not_crash(self):
        a = A.parse_adr("0001-a.md", adr_text(id_="0001", status="superseded by ADR-9999"),
                        known_reqs={"REQ-001"})
        A.link_supersession([a])
        self.assertEqual(a.superseded_by, "9999")


class TestScanAdrs(unittest.TestCase):
    def test_empty_directory_yields_no_records(self, tmp_path=None):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(A.scan_adrs(Path(d), set()), [])

    def test_missing_directory_yields_no_records_not_a_crash(self):
        self.assertEqual(A.scan_adrs(Path("/nonexistent/adr/dir"), set()), [])

    def test_readme_is_excluded_but_records_are_included(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "README.md").write_text("not a record")
            (d / "0001-a.md").write_text(adr_text(id_="0001"))
            records = A.scan_adrs(d, {"REQ-001"})
            self.assertEqual([r.filename for r in records], ["0001-a.md"])

    def test_malformed_file_is_listed_not_dropped(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "0001-a.md").write_text(adr_text(id_="0001"))
            (d / "0002-broken.md").write_text("not an adr at all")
            records = A.scan_adrs(d, {"REQ-001"})
            self.assertEqual(len(records), 2)
            broken = next(r for r in records if r.filename == "0002-broken.md")
            self.assertIsNotNone(broken.error)


class TestRenderBody(unittest.TestCase):
    def test_leading_bold_label_is_converted(self):
        html = A.render_body("- **Cost:** low")
        self.assertIn("<strong>Cost:</strong> low", html)

    def test_literal_double_asterisk_glob_is_not_treated_as_bold(self):
        # Real ADR prose has literal `**` globs (e.g. `.github/workflows/**`)
        # paragraphs apart from each other; a naive "**...**" scan pairs them
        # and bolds everything in between.
        text = ("First mentions `foo/**` here, then much later in the same "
                "paragraph mentions `bar/**` again.")
        html = A.render_body(text)
        self.assertNotIn("<strong>", html)
        self.assertIn("foo/**", html)
        self.assertIn("bar/**", html)

    def test_wrapped_bullet_continuation_joins_into_one_item(self):
        html = A.render_body("- **Cost:** first line\n  second line continues")
        self.assertIn("<li><strong>Cost:</strong> first line second line continues</li>", html)

    def test_h3_subheading_becomes_h5(self):
        html = A.render_body("### Option A: do it\n\nsome text")
        self.assertIn("<h5>Option A: do it</h5>", html)
        self.assertIn("<p>some text</p>", html)


class TestRenderHtml(unittest.TestCase):
    def test_renders_self_contained_html_and_escapes_titles(self):
        r = A.parse_adr("0001-a.md", adr_text(title="fix <script>alert(1)</script>"),
                        known_reqs={"REQ-001"})
        html = A.render_html([r], {"repo": "a/b", "repo_url": "https://github.com/a/b",
                                   "generated_at": "now"})
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>alert", html)
        self.assertIn("ADR-0001", html)

    def test_empty_list_still_renders_a_page(self):
        html = A.render_html([], {"repo": "a/b", "repo_url": "https://github.com/a/b",
                                  "generated_at": "now"})
        self.assertIn("No ADR records found", html)

    def test_req_link_points_at_traceability_anchor(self):
        r = A.parse_adr("0001-a.md", adr_text(requirement="REQ-001"), known_reqs={"REQ-001"})
        html = A.render_html([r], {"repo": "a/b", "repo_url": "https://github.com/a/b"})
        self.assertIn('href="traceability.html#REQ-001"', html)

    def test_unknown_req_is_marked_not_linked(self):
        r = A.parse_adr("0001-a.md", adr_text(requirement="REQ-999"), known_reqs={"REQ-001"})
        html = A.render_html([r], {"repo": "a/b", "repo_url": "https://github.com/a/b"})
        self.assertNotIn('href="traceability.html#REQ-999"', html)
        self.assertIn("REQ-999", html)

    def test_superseded_chain_renders_both_directions(self):
        old = A.parse_adr("0001-old.md", adr_text(id_="0001", status="superseded by ADR-0002"),
                          known_reqs={"REQ-001"})
        new = A.parse_adr("0002-new.md", adr_text(id_="0002"), known_reqs={"REQ-001"})
        A.link_supersession([old, new])
        html = A.render_html([old, new], {"repo": "a/b", "repo_url": "https://github.com/a/b"})
        self.assertIn('href="#adr-0002"', html)
        self.assertIn('href="#adr-0001"', html)
        self.assertIn("Supersedes", html)

    def test_parse_errors_are_listed_on_the_page(self):
        broken = A.parse_adr("weird.md", "not an adr", known_reqs=set())
        html = A.render_html([broken], {"repo": "a/b", "repo_url": "https://github.com/a/b"})
        self.assertIn("parse error", html)
        self.assertIn("weird.md", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
