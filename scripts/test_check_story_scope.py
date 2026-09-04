#!/usr/bin/env python3
"""Tests for the story-scope check (#168).

Two groups. `TestUnits` pins the six required cases directly (in-scope,
out-of-scope, two-scope span, no role label, unparseable body, plus
extraction itself). `TestAgainstRealIssues` replays it against the six
stories that motivated it and three real single-scope stories that did
not, using their real content — see each fixture for its source.

    python3 scripts/test_check_story_scope.py
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
spec = importlib.util.spec_from_file_location("check_story_scope", HERE / "check-story-scope.py")
S = importlib.util.module_from_spec(spec)
sys.modules["check_story_scope"] = S
spec.loader.exec_module(S)


def analyze(body, role=None):
    return S.analyze(body, role)


class TestExtraction(unittest.TestCase):
    def test_backticked_path_with_known_extension(self):
        self.assertEqual(S.extract_paths("the deliverable is `scripts/check-adr.py`, plus tests"),
                         ["scripts/check-adr.py"])

    def test_bare_path_with_known_extension(self):
        self.assertEqual(S.extract_paths("changed in policies/gates.yaml today"),
                         ["policies/gates.yaml"])

    def test_glob_pattern_is_extracted(self):
        self.assertEqual(S.extract_paths("`ceremonies/**` is newly in scope"),
                         ["ceremonies/**"])

    def test_bare_directory_mention_is_dropped(self):
        # No filename or glob after the slash — naming a directory is not
        # proposing to write a specific file in it.
        self.assertEqual(S.extract_paths("writes nothing into `prds/` or `requirements/`"), [])

    def test_unknown_extension_is_dropped(self):
        self.assertEqual(S.extract_paths("writes `site/decisions.html`"), [])

    def test_no_slash_is_dropped(self):
        self.assertEqual(S.extract_paths("reuses `gate-check.py`'s matched_rules"), [])

    def test_reference_word_before_a_path_is_dropped(self):
        self.assertEqual(S.extract_paths("using `sla_hours` from `policies/gates.yaml`"), [])
        self.assertEqual(S.extract_paths("vocabulary matches `policies/gates.yaml`"), [])

    def test_dedupes_in_first_seen_order(self):
        self.assertEqual(
            S.extract_paths("`scripts/a.py` ... again `scripts/a.py` ... `scripts/b.py`"),
            ["scripts/a.py", "scripts/b.py"])


class TestUnits(unittest.TestCase):
    """The six cases the acceptance criteria name explicitly."""

    def test_in_scope(self):
        body = "## Acceptance criteria\n\n- [ ] `scripts/foo.py` does the thing\n"
        result = analyze(body, "developer")
        self.assertEqual(result["out_of_scope"], [])
        self.assertFalse(result["flagged"])

    def test_out_of_scope(self):
        body = "## Acceptance criteria\n\n- [ ] `scripts/foo.py` does the thing\n"
        result = analyze(body, "architect")
        self.assertEqual([e["path"] for e in result["out_of_scope"]], ["scripts/foo.py"])
        self.assertIn("developer", result["out_of_scope"][0]["capable_roles"])
        self.assertTrue(result["flagged"])

    def test_two_scope_span(self):
        # scripts/ (developer) and adrs/ (architect) — no single role covers
        # both. Flagged as a span even though the assigned role (developer)
        # covers one of the two paths named.
        body = ("## Acceptance criteria\n\n"
                "- [ ] `scripts/render-adr.py` renders the page\n"
                "- [ ] `adrs/template.py` is the shared template\n")
        result = analyze(body, "developer")
        # developer covers scripts/render-adr.py but not adrs/template.py
        self.assertEqual([e["path"] for e in result["out_of_scope"]], ["adrs/template.py"])
        self.assertTrue(result["spanning"])
        self.assertIn("architect", result["spanning"])
        self.assertIn("developer", result["spanning"])
        self.assertTrue(result["flagged"])

    def test_no_role_label(self):
        body = "## Acceptance criteria\n\n- [ ] `scripts/foo.py` does the thing\n"
        result = analyze(body, None)
        self.assertIsNone(result["role"])
        self.assertEqual(result["out_of_scope"], [])   # cannot be checked without a role
        self.assertFalse(result["flagged"])

    def test_unparseable_body(self):
        for body in ("", "no headings here, just prose about scripts/foo.py",
                     "## Scope\n\nOnly a scope section, no criteria heading.\n"):
            with self.subTest(body=body[:20]):
                result = analyze(body, "developer")
                self.assertIsNone(result["section"])
                self.assertFalse(result["flagged"])


class TestReport(unittest.TestCase):
    def test_clean_report_says_so(self):
        result = analyze("## Acceptance criteria\n\n- [ ] `scripts/foo.py`\n", "developer")
        self.assertIn("inside", S.render_report(result, 1))

    def test_unparseable_report_says_so(self):
        result = analyze("", "developer")
        self.assertIn("No `## Acceptance criteria`", S.render_report(result, 1))

    def test_flagged_report_names_the_path_and_capable_role(self):
        result = analyze("## Acceptance criteria\n\n- [ ] `scripts/foo.py`\n", "architect")
        report = S.render_report(result, 1)
        self.assertIn("scripts/foo.py", report)
        self.assertIn("developer", report)


class TestAgainstRealIssues(unittest.TestCase):
    """Replayed against the six stories P1-17 (#168) names and three real
    single-scope stories it did not.

    GitHub does not expose an issue body's edit history via the API, and
    all six were amended in place once the mistake was found — so the six
    fixtures below reconstruct only the `## Acceptance criteria` paths
    P1-17's own table states each issue originally demanded, under each
    issue's *historical* role label (the one it carried when the mistake
    was made, before a human corrected it). The three clean fixtures are
    verbatim `## Acceptance criteria` sections copied from the live
    issues, fetched with `gh issue view <n> --json body`.
    """

    # -- the six --------------------------------------------------------

    def test_issue_52_developer_demanded_policy(self):
        body = ("## Acceptance criteria\n\n"
                "- [ ] `docs/gate-sla.md` documents the mechanism\n"
                "- [ ] `policies/gates.yaml` gains an `sla_comment` marker field\n")
        result = analyze(body, "developer")
        self.assertTrue(result["flagged"])
        paths = [e["path"] for e in result["out_of_scope"]]
        self.assertIn("policies/gates.yaml", paths)
        self.assertIn("delivery-lead",
                      next(e for e in result["out_of_scope"]
                           if e["path"] == "policies/gates.yaml")["capable_roles"])

    def test_issue_103_architect_demanded_a_script(self):
        body = ("## Acceptance criteria\n\n"
                "- [ ] `adrs/0001-per-role-credentials.md` records the decision\n"
                "- [ ] `scripts/check-adr.py` validates every ADR against the template\n")
        result = analyze(body, "architect")
        self.assertTrue(result["flagged"])
        paths = [e["path"] for e in result["out_of_scope"]]
        self.assertEqual(paths, ["scripts/check-adr.py"])
        self.assertIn("developer", result["out_of_scope"][0]["capable_roles"])

    def test_issue_114_delivery_lead_demanded_a_script(self):
        body = ("## Acceptance criteria\n\n"
                "- [ ] `ceremonies/planning.yaml` declares planning's cadence and owner\n"
                "- [ ] `scripts/check-ceremonies.py` validates all five declarations\n")
        result = analyze(body, "delivery-lead")
        self.assertTrue(result["flagged"])
        paths = [e["path"] for e in result["out_of_scope"]]
        self.assertEqual(paths, ["scripts/check-ceremonies.py"])
        self.assertIn("developer", result["out_of_scope"][0]["capable_roles"])

    def test_issue_116_delivery_lead_demanded_a_script(self):
        body = ("## Acceptance criteria\n\n"
                "- [ ] `policies/signoff.yaml` declares sign-off scopes and evidence\n"
                "- [ ] `scripts/signoff-check.py` classifies an item's sign-off state\n")
        result = analyze(body, "delivery-lead")
        self.assertTrue(result["flagged"])
        paths = [e["path"] for e in result["out_of_scope"]]
        self.assertEqual(paths, ["scripts/signoff-check.py"])
        self.assertIn("developer", result["out_of_scope"][0]["capable_roles"])

    def test_issue_121_delivery_lead_demanded_a_script(self):
        body = ("## Acceptance criteria\n\n"
                "- [ ] `policies/environments.yaml` declares the four environments\n"
                "- [ ] `scripts/check-environments.py` checks every environment exists\n")
        result = analyze(body, "delivery-lead")
        self.assertTrue(result["flagged"])
        paths = [e["path"] for e in result["out_of_scope"]]
        self.assertEqual(paths, ["scripts/check-environments.py"])
        self.assertIn("developer", result["out_of_scope"][0]["capable_roles"])

    def test_issue_159_product_manager_demanded_dashboards(self):
        body = ("## Acceptance criteria\n\n"
                "- [ ] `requirements/coverage.yaml` notes match their computed checks\n"
                "- [ ] `dashboards/status.py` flags a note that contradicts its checks\n"
                "- [ ] `dashboards/test_status.py` covers the contradiction case\n")
        result = analyze(body, "product-manager")
        self.assertTrue(result["flagged"])
        paths = {e["path"] for e in result["out_of_scope"]}
        self.assertEqual(paths, {"dashboards/status.py", "dashboards/test_status.py"})
        for e in result["out_of_scope"]:
            self.assertIn("developer", e["capable_roles"])
        self.assertTrue(result["spanning"])

    # -- three that were not the problem --------------------------------

    def test_issue_104_developer_dashboards_reports_clean(self):
        # `gh issue view 104 --json body`, `## Acceptance criteria` section.
        body = (
            "## Acceptance criteria\n\n"
            "- [ ] `dashboards/decisions.py` writes `site/decisions.html`, "
            "self-contained, no external assets\n"
            "- [ ] Reuses `gate-check.py`'s `matched_rules`/`role_can_write` "
            "— no second copy of the rules\n"
            "- [ ] \"Waiting on you\" lists every open `needs-human` item and "
            "every critical `status:needs-refinement` item, oldest first, "
            "with the rule's own `because` text\n"
            "- [ ] Past-SLA rows are visibly distinguished, using `sla_hours` "
            "from `policies/gates.yaml` rather than a literal\n"
            "- [ ] \"Decided\" attributes each decision to the actor from the "
            "label event; bot actors are never shown as human decisions\n"
            "- [ ] Undeterminable values render as `unknown`, never omitted "
            "or guessed\n"
            "- [ ] `dashboards/test_decisions.py` covers: empty state, a "
            "past-SLA item, a bot-applied label excluded from the log, and "
            "an item with no determinable reason\n"
            "- [ ] `build.py`'s index links the page when it exists (it "
            "already links whichever pages are present)\n"
            "\n## Out of scope\n\n"
            "Adding the build step to `.github/workflows/dashboards.yml` — "
            "that path is devops-owned.\n"
        )
        result = analyze(body, "developer")
        self.assertEqual(result["out_of_scope"], [])
        self.assertFalse(result["flagged"])

    def test_issue_118_developer_transcript_to_prd_reports_clean(self):
        # `gh issue view 118 --json body`, `## Acceptance criteria` section.
        body = (
            "## Acceptance criteria\n\n"
            "- [ ] `scripts/transcript-to-prd.py --in <file> --out <file>` "
            "produces a draft with candidate REQs\n"
            "- [ ] Every candidate carries its source quote; candidates "
            "without one are dropped and counted in the summary\n"
            "- [ ] Contradictions surface as open questions, never silently "
            "resolved\n"
            "- [ ] Writes nothing into `prds/` or `requirements/` — output "
            "path only\n"
            "- [ ] Tests cover: empty transcript, a transcript with no "
            "requirements in it, contradictory statements, and a quote "
            "spanning multiple lines\n"
            "- [ ] No network and no model call; the test suite runs "
            "offline\n"
        )
        result = analyze(body, "developer")
        self.assertEqual(result["out_of_scope"], [])
        self.assertFalse(result["flagged"])

    def test_issue_126_developer_adr_validator_reports_clean(self):
        # `gh issue view 126 --json body`, `## Acceptance criteria` section.
        # No path survives extraction at all here (`adrs/` is a bare
        # directory mention, dropped) — the clean report for an empty
        # path list, not just a scoped one.
        body = (
            "## Acceptance criteria\n\n"
            "- [ ] Validates every record in `adrs/` and exits non-zero on "
            "any violation\n"
            "- [ ] Reports every violation found, not just the first — a "
            "validator that stops at one error takes N runs to fix N "
            "problems\n"
            "- [ ] Tests cover each failure mode above plus the happy path, "
            "and run against fixtures rather than the live `adrs/` "
            "directory\n"
            "- [ ] Passes against the seven records merged by #111 — if it "
            "does not, say whether the records or the validator is wrong "
            "rather than loosening the check to fit\n"
            "- [ ] Wired into CI; if the workflow edit is out of scope, "
            "write the exact patch on this issue and stop\n"
        )
        result = analyze(body, "developer")
        self.assertEqual(result["paths"], [])
        self.assertEqual(result["out_of_scope"], [])
        self.assertFalse(result["flagged"])


class TestCapableRoles(unittest.TestCase):
    def test_no_role_can_write_an_unscoped_path(self):
        self.assertEqual(S.capable_roles("nowhere/at/all.py"), [])

    def test_multiple_roles_can_be_capable(self):
        # scripts/** (developer) and scripts/*deploy*, scripts/*release*
        # (devops) share the same coarse root — see gate-check.py's
        # `_covers`, reused here rather than re-implemented.
        roles = S.capable_roles("scripts/check-adr.py")
        self.assertIn("developer", roles)


if __name__ == "__main__":
    unittest.main()
