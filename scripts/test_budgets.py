#!/usr/bin/env python3
"""Tests for budget resolution and spend accounting.

    python3 scripts/test_budgets.py
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


RB = load("read_budget", "read-budget.py")
SR = load("spend_report", "spend-report.py")


POLICY = """\
version: 0
role: widget

budgets:
  turns: 12
  tokens: 90000
  wall_clock_minutes: 20
  max_retries: 1
  on_breach: escalate

forbidden:
  - push_to_default_branch
"""


class PackFixture:
    def __init__(self, policy_text: str | None, role="widget"):
        self.tmp = Path(tempfile.mkdtemp())
        if policy_text is not None:
            d = self.tmp / "role-packs" / role
            d.mkdir(parents=True)
            (d / "policy.yaml").write_text(policy_text)
        self._saved = RB.REPO_ROOT
        RB.REPO_ROOT = self.tmp

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        RB.REPO_ROOT = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestBudgetResolution(unittest.TestCase):
    def test_policy_wins_over_defaults(self):
        with PackFixture(POLICY):
            budget, source = RB.resolve("widget", {})
        self.assertEqual(budget["turns"], 12)
        self.assertEqual(budget["tokens"], 90000)
        self.assertEqual(budget["max_retries"], 1)
        self.assertIn("policy.yaml", source)

    def test_override_wins_over_policy(self):
        with PackFixture(POLICY):
            budget, _ = RB.resolve("widget", {"turns": 50})
        self.assertEqual(budget["turns"], 50)
        self.assertEqual(budget["tokens"], 90000, "an override of one line "
                                                  "must not reset the others")

    def test_zero_override_means_use_the_policy(self):
        with PackFixture(POLICY):
            budget, _ = RB.resolve("widget", {"turns": 0})
        self.assertEqual(budget["turns"], 12)

    def test_missing_pack_falls_back_to_defaults_not_to_nothing(self):
        with PackFixture(None):
            budget, source = RB.resolve("widget", {})
        self.assertEqual(budget, RB.DEFAULTS)
        self.assertIn("built-in defaults", source)

    def test_a_policy_key_the_dispatcher_does_not_know_is_ignored(self):
        with PackFixture(POLICY.replace("  on_breach: escalate",
                                        "  on_breach: escalate\n  future_knob: 7")):
            budget, _ = RB.resolve("widget", {})
        self.assertNotIn("future_knob", budget)
        self.assertEqual(budget["turns"], 12)

    def test_zero_turns_is_refused(self):
        with PackFixture(POLICY.replace("turns: 12", "turns: 0")):
            with self.assertRaises(SystemExit) as ctx:
                RB.resolve("widget", {})
            self.assertIn("zero-turn", str(ctx.exception))

    def test_a_non_numeric_budget_is_refused(self):
        with PackFixture(POLICY.replace("tokens: 90000", "tokens: lots")):
            with self.assertRaises(SystemExit) as ctx:
                RB.resolve("widget", {})
            self.assertIn("not a number", str(ctx.exception))


class TestFallbackParser(unittest.TestCase):
    """The dispatcher runs on a bare runner; PyYAML may not be there."""

    def test_reads_the_flat_block(self):
        self.assertEqual(RB.parse_budgets_fallback(POLICY), {
            "turns": 12, "tokens": 90000, "wall_clock_minutes": 20,
            "max_retries": 1, "on_breach": "escalate",
        })

    def test_stops_at_the_next_top_level_key(self):
        self.assertNotIn("forbidden", RB.parse_budgets_fallback(POLICY))

    def test_strips_trailing_comments(self):
        text = "budgets:\n  turns: 5    # per session\n"
        self.assertEqual(RB.parse_budgets_fallback(text)["turns"], 5)

    def test_missing_block_raises(self):
        with self.assertRaises(KeyError):
            RB.parse_budgets_fallback("role: widget\n")

    def test_nested_budget_is_an_error_not_a_silent_miss(self):
        text = "budgets:\n  limits:\n    turns: 5\n"
        with self.assertRaises(ValueError) as ctx:
            RB.parse_budgets_fallback(text)
        self.assertIn("must be flat", str(ctx.exception))

    def test_agrees_with_pyyaml_on_the_real_developer_pack(self):
        path = HERE.parent / "role-packs" / "developer" / "policy.yaml"
        if not path.is_file():
            self.skipTest("developer pack lands with P0-3")
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")
        text = path.read_text()
        native = yaml.safe_load(text)["budgets"]
        fallback = RB.parse_budgets_fallback(text)
        self.assertEqual({k: native[k] for k in fallback}, fallback)


def execution(**result) -> str:
    return json.dumps([
        {"type": "system", "subtype": "init"},
        {"type": "assistant", "message": {}},
        {"type": "result", **result},
    ])


USAGE = {"input_tokens": 1000, "output_tokens": 2000,
         "cache_read_input_tokens": 30000, "cache_creation_input_tokens": 4000}


class TestSpendReport(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, text: str) -> Path:
        p = self.tmp / "exec.json"
        p.write_text(text)
        return p

    def test_totals_include_cache_tokens(self):
        p = self.write(execution(num_turns=9, usage=USAGE, duration_ms=600000,
                                 total_cost_usd=0.42))
        result, note = SR.load_execution(p)
        spend = SR.summarise(result)
        self.assertEqual(note, "")
        self.assertEqual(spend["turns"], 9)
        self.assertEqual(spend["total_tokens"], 37000)
        self.assertEqual(spend["wall_clock_minutes"], 10.0)
        self.assertEqual(spend["cost_usd"], 0.42)

    def test_inside_budget(self):
        p = self.write(execution(num_turns=9, usage=USAGE, duration_ms=600000))
        rows = SR.check(SR.summarise(SR.load_execution(p)[0]),
                        {"turns": 30, "tokens": 400000, "wall_clock_minutes": 45})
        self.assertFalse(any(r["breached"] for r in rows))

    def test_token_breach_is_detected(self):
        p = self.write(execution(num_turns=9, usage=USAGE, duration_ms=600000))
        rows = SR.check(SR.summarise(SR.load_execution(p)[0]),
                        {"turns": 30, "tokens": 1000, "wall_clock_minutes": 45})
        self.assertEqual([r["label"] for r in rows if r["breached"]], ["tokens"])

    def test_wall_clock_breach_is_detected(self):
        p = self.write(execution(num_turns=2, usage=USAGE, duration_ms=3_600_000))
        rows = SR.check(SR.summarise(SR.load_execution(p)[0]),
                        {"turns": 30, "tokens": 400000, "wall_clock_minutes": 45})
        self.assertEqual([r["label"] for r in rows if r["breached"]], ["wall clock"])

    def test_several_lines_can_breach_at_once(self):
        p = self.write(execution(num_turns=99, usage=USAGE, duration_ms=3_600_000))
        rows = SR.check(SR.summarise(SR.load_execution(p)[0]),
                        {"turns": 30, "tokens": 100, "wall_clock_minutes": 45})
        self.assertEqual([r["label"] for r in rows if r["breached"]],
                         ["turns", "tokens", "wall clock"])

    def test_jsonl_form_is_accepted(self):
        p = self.write('{"type":"system"}\n'
                       '{"type":"result","num_turns":3,"usage":{"input_tokens":5}}\n')
        result, note = SR.load_execution(p)
        self.assertEqual(note, "")
        self.assertEqual(SR.summarise(result)["turns"], 3)

    def test_a_missing_log_is_unknown_not_a_breach(self):
        result, note = SR.load_execution(self.tmp / "nope.json")
        rows = SR.check(SR.summarise(result), {"turns": 1, "tokens": 1})
        self.assertIn("no execution log", note)
        self.assertFalse(any(r["breached"] for r in rows),
                         "an unmeasured session must not fire the escalation ladder")

    def test_a_log_without_a_result_record_is_unknown(self):
        p = self.write(json.dumps([{"type": "assistant"}]))
        _, note = SR.load_execution(p)
        self.assertIn("no result record", note)

    def test_a_corrupt_log_is_unknown_not_a_crash(self):
        p = self.write("{not json at all")
        result, note = SR.load_execution(p)
        self.assertEqual(result, {})
        self.assertIn("unreadable", note)

    def test_rendered_table_marks_the_breach_and_shows_cost(self):
        p = self.write(execution(num_turns=99, usage=USAGE, duration_ms=600000,
                                 total_cost_usd=1.2345))
        spend = SR.summarise(SR.load_execution(p)[0])
        rows = SR.check(spend, {"turns": 30, "tokens": 400000,
                                "wall_clock_minutes": 45})
        md = SR.render(rows, spend, "")
        self.assertIn("| turns (turns) | 99 | 30 | over |", md)
        self.assertIn("1.2345", md)
        self.assertIn("cache read", md)

    def test_unmeasured_session_says_so_on_the_page(self):
        md = SR.render(SR.check(SR.summarise({}), {"turns": 30}), SR.summarise({}),
                       "no execution log was produced")
        self.assertIn("unknown", md)
        self.assertIn("reported rather than", md)


if __name__ == "__main__":
    unittest.main(verbosity=2)
