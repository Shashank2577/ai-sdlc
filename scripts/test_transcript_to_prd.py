#!/usr/bin/env python3
"""Tests for the transcript-to-draft-PRD extractor (REQ-008).

extract() and render() are pure functions of the transcript text, so the
whole pipeline — parsing, trigger detection, contradiction/ambiguity
flagging, quote provenance — is testable without touching the filesystem.
A handful of CLI-level tests cover the --in/--out contract, including the
guard against writing into prds/ or requirements/.

    python3 scripts/test_transcript_to_prd.py
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("transcript_to_prd", HERE / "transcript-to-prd.py")
T = importlib.util.module_from_spec(spec)
sys.modules["transcript_to_prd"] = T
spec.loader.exec_module(T)


class TestEmptyTranscript(unittest.TestCase):
    def test_empty_string_produces_no_candidates_or_questions(self):
        result = T.extract("")
        self.assertEqual(result.candidates, [])
        self.assertEqual(result.open_questions, [])
        self.assertEqual(result.dropped_no_quote, 0)

    def test_whitespace_only_transcript_does_not_crash(self):
        result = T.extract("   \n\n  \n")
        self.assertEqual(result.candidates, [])

    def test_render_of_empty_result_says_so_explicitly(self):
        doc = T.render(T.extract(""), "empty.txt", "empty.txt", 0)
        self.assertIn("No candidate requirements were extracted", doc)
        self.assertIn("None raised", doc)
        self.assertIn("Candidate requirements: 0", doc)


class TestNoRequirementsInTranscript(unittest.TestCase):
    def test_pure_narration_yields_no_candidates(self):
        transcript = (
            "Alice: The meeting started on time.\n\n"
            "Bob: Everyone introduced themselves.\n\n"
            "Alice: It was a nice, sunny day outside.\n"
        )
        result = T.extract(transcript)
        self.assertEqual(result.candidates, [])
        self.assertEqual(result.open_questions, [])


class TestQuoteSpansMultipleLines(unittest.TestCase):
    def test_a_wrapped_utterance_is_joined_into_one_verbatim_quote(self):
        transcript = (
            "Priya: We absolutely need the export\n"
            "feature to support CSV and PDF formats.\n"
        )
        result = T.extract(transcript)
        self.assertEqual(len(result.candidates), 1)
        cand = result.candidates[0]
        self.assertEqual(
            cand.quote,
            "We absolutely need the export feature to support CSV and PDF formats."
        )
        self.assertNotIn("\n", cand.quote)
        self.assertEqual(cand.speaker, "Priya")
        self.assertEqual(cand.line, 1)  # traceable to where the quote starts

    def test_every_candidate_carries_its_source_quote(self):
        transcript = "Dana: We need a working export button.\n"
        result = T.extract(transcript)
        self.assertEqual(len(result.candidates), 1)
        self.assertTrue(result.candidates[0].quote)

    def test_a_speaker_label_with_parentheses_is_still_recognized(self):
        transcript = "Client (Jo): We need SSO login.\n"
        result = T.extract(transcript)
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].speaker, "Client (Jo)")
        self.assertEqual(result.candidates[0].quote, "We need SSO login.")


class TestContradictions(unittest.TestCase):
    def test_conflicting_statements_become_an_open_question_not_a_silent_pick(self):
        transcript = (
            "Alice: The system must support SSO login.\n\n"
            "Bob: Actually, the system should not support SSO login due to "
            "compliance concerns.\n"
        )
        result = T.extract(transcript)
        # Both statements still stand as candidates — the script does not
        # decide which one is right.
        self.assertEqual(len(result.candidates), 2)
        self.assertEqual(result.contradiction_count, 1)
        contradictions = [oq for oq in result.open_questions if oq.kind == "contradiction"]
        self.assertEqual(len(contradictions), 1)
        oq = contradictions[0]
        self.assertEqual(len(oq.quotes), 2)
        self.assertIn("SSO", oq.quotes[0][0])
        self.assertIn("SSO", oq.quotes[1][0])
        self.assertIn("not resolved automatically", oq.detail.lower())

    def test_unrelated_requirements_are_not_flagged_as_contradictions(self):
        transcript = (
            "Alice: We need SSO login.\n\n"
            "Bob: We also need a CSV export button.\n"
        )
        result = T.extract(transcript)
        self.assertEqual(result.contradiction_count, 0)


class TestAmbiguity(unittest.TestCase):
    def test_a_hedge_is_raised_as_an_open_question_not_a_candidate(self):
        transcript = "Casey: Maybe we need multi-tenant support, I'm not sure.\n"
        result = T.extract(transcript)
        self.assertEqual(result.candidates, [])
        self.assertEqual(result.ambiguity_count, 1)
        self.assertEqual(result.open_questions[0].kind, "ambiguity")
        self.assertIn("multi-tenant", result.open_questions[0].quotes[0][0])


class TestDroppedWithoutQuote(unittest.TestCase):
    def test_a_candidate_with_no_quote_is_dropped_not_invented(self):
        self.assertIsNone(T.make_candidate(1, "   ", "Alice", 3))
        self.assertIsNone(T.make_candidate(1, "", None, 1))

    def test_a_valid_sentence_produces_a_real_candidate(self):
        cand = T.make_candidate(1, "We need X.", "Alice", 3)
        self.assertIsNotNone(cand)
        self.assertEqual(cand.quote, "We need X.")
        self.assertEqual(cand.id, "CAND-REQ-001")


class TestDeterminism(unittest.TestCase):
    def test_the_same_transcript_always_extracts_the_same_result(self):
        transcript = (
            "Alice: We need SSO login.\n\n"
            "Bob: The system must not allow SSO login for contractors.\n"
        )
        first = T.render(T.extract(transcript), "t.txt", "t.txt", 2)
        second = T.render(T.extract(transcript), "t.txt", "t.txt", 2)
        self.assertEqual(first, second)


class TestCli(unittest.TestCase):
    def test_end_to_end_writes_a_draft_with_summary_counts(self):
        with tempfile.TemporaryDirectory() as d:
            in_path = Path(d) / "call.txt"
            out_path = Path(d) / "draft.md"
            in_path.write_text("Alice: We need SSO login by Q3.\n")
            rc = T.main(["--in", str(in_path), "--out", str(out_path)])
            self.assertEqual(rc, 0)
            doc = out_path.read_text()
            self.assertIn("CAND-REQ-001", doc)
            self.assertIn("SSO login by Q3", doc)
            self.assertIn("Candidate requirements: 1", doc)

    def test_refuses_to_write_into_requirements_dir(self):
        with tempfile.TemporaryDirectory() as d:
            in_path = Path(d) / "call.txt"
            in_path.write_text("Alice: We need SSO login.\n")
            bad_out = T.REPO_ROOT / "requirements" / "sneaky-draft.md"
            with self.assertRaises(SystemExit):
                T.main(["--in", str(in_path), "--out", str(bad_out)])
            self.assertFalse(bad_out.exists())

    def test_refuses_to_write_into_prds_dir(self):
        with tempfile.TemporaryDirectory() as d:
            in_path = Path(d) / "call.txt"
            in_path.write_text("Alice: We need SSO login.\n")
            bad_out = T.REPO_ROOT / "prds" / "sneaky-draft.md"
            with self.assertRaises(SystemExit):
                T.main(["--in", str(in_path), "--out", str(bad_out)])
            self.assertFalse(bad_out.exists())

    def test_missing_input_file_exits_cleanly(self):
        with tempfile.TemporaryDirectory() as d:
            out_path = Path(d) / "draft.md"
            with self.assertRaises(SystemExit):
                T.main(["--in", str(Path(d) / "nope.txt"), "--out", str(out_path)])


if __name__ == "__main__":
    unittest.main()
