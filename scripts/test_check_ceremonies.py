#!/usr/bin/env python3
"""Tests for scripts/check-ceremonies.py.

Fixtures, not the live `ceremonies/` directory — a fixture pins the exact
shape a failure mode needs; the live directory changes as declarations are
added and would make these tests brittle for the wrong reason. The one
exception is `test_the_five_merged_declarations_pass`, which is the
regression that ties this suite back to the real files (AC: "passes
against the five declarations merged by #132").

    python3 scripts/test_check_ceremonies.py
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

spec = importlib.util.spec_from_file_location("check_ceremonies", HERE / "check-ceremonies.py")
C = importlib.util.module_from_spec(spec)
sys.modules["check_ceremonies"] = C
spec.loader.exec_module(C)


VALID = {
    "ceremony": "standup",
    "cadence": "15 6 * * *",
    "role": "devops",
    "consumes": ["commit pushes"],
    "produces": ["a dashboard digest"],
    "artifact_is": "dashboard page",
    "escalates_when": ["a blocked item sits past SLA"],
    "owner": "devops",
}


def dump(data: dict) -> str:
    import yaml
    return yaml.safe_dump(data, sort_keys=False)


class CeremoniesFixture(unittest.TestCase):
    """Builds a scratch `ceremonies/` + `role-packs/` pair per test."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.ceremonies = self.root / "ceremonies"
        self.packs = self.root / "role-packs"
        self.ceremonies.mkdir()
        self.packs.mkdir()
        for role in ("developer", "devops", "product-manager", "orchestrator",
                     "techwriter", "qa", "architect", "delivery-lead"):
            (self.packs / role).mkdir()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, name: str, data: dict) -> Path:
        path = self.ceremonies / name
        path.write_text(dump(data))
        return path

    def validate(self) -> list[str]:
        return C.validate_all(self.ceremonies, self.packs)


class TestHappyPath(CeremoniesFixture):
    def test_a_single_valid_ceremony_passes(self):
        self.write("standup.yaml", VALID)
        self.assertEqual(self.validate(), [])

    def test_two_valid_ceremonies_with_different_cadences_pass(self):
        self.write("standup.yaml", VALID)
        other = dict(VALID, ceremony="retro", cadence="0 7 * * 1",
                     role="devops", artifact_is="new issues")
        self.write("retro.yaml", other)
        self.assertEqual(self.validate(), [])


class TestMissingKey(CeremoniesFixture):
    def test_missing_required_key_fails(self):
        data = dict(VALID)
        del data["owner"]
        self.write("standup.yaml", data)
        errors = self.validate()
        self.assertEqual(len(errors), 1)
        self.assertIn("missing required key", errors[0])
        self.assertIn("owner", errors[0])

    def test_missing_multiple_keys_are_all_named(self):
        data = dict(VALID)
        del data["owner"]
        del data["cadence"]
        self.write("standup.yaml", data)
        [error] = self.validate()
        self.assertIn("cadence", error)
        self.assertIn("owner", error)


class TestUnknownKey(CeremoniesFixture):
    def test_unknown_key_fails(self):
        data = dict(VALID, extra_field="a private extension")
        self.write("standup.yaml", data)
        errors = self.validate()
        self.assertEqual(len(errors), 1)
        self.assertIn("unknown key", errors[0])
        self.assertIn("extra_field", errors[0])


class TestUnknownRole(CeremoniesFixture):
    def test_role_not_a_real_pack_fails(self):
        data = dict(VALID, role="delivery-manager")
        self.write("standup.yaml", data)
        errors = self.validate()
        self.assertEqual(len(errors), 1)
        self.assertIn("delivery-manager", errors[0])
        self.assertIn("does not name a real pack", errors[0])

    def test_role_is_read_from_the_filesystem_not_hardcoded(self):
        (self.packs / "delivery-manager").mkdir()
        data = dict(VALID, role="delivery-manager")
        self.write("standup.yaml", data)
        self.assertEqual(self.validate(), [])


class TestUnknownArtifactIs(CeremoniesFixture):
    def test_unknown_artifact_kind_fails(self):
        data = dict(VALID, artifact_is="a Slack message")
        self.write("standup.yaml", data)
        errors = self.validate()
        self.assertEqual(len(errors), 1)
        self.assertIn("artifact_is", errors[0])
        self.assertIn("a Slack message", errors[0])

    def test_each_known_kind_is_accepted(self):
        for kind in C.ARTIFACT_KINDS:
            data = dict(VALID, artifact_is=kind)
            self.write("standup.yaml", data)
            self.assertEqual(self.validate(), [], f"kind {kind!r} should pass")
            (self.ceremonies / "standup.yaml").unlink()


class TestDuplicateCadence(CeremoniesFixture):
    def test_two_files_sharing_a_cadence_fails(self):
        self.write("standup.yaml", VALID)
        other = dict(VALID, ceremony="retro", role="devops")
        self.write("retro.yaml", other)
        errors = self.validate()
        self.assertEqual(len(errors), 1)
        self.assertIn("cadence", errors[0])
        self.assertIn("collides", errors[0])

    def test_distinct_cadences_do_not_collide(self):
        self.write("standup.yaml", VALID)
        other = dict(VALID, ceremony="retro", cadence="0 7 * * 1", role="devops")
        self.write("retro.yaml", other)
        self.assertEqual(self.validate(), [])


class TestEmptyLists(CeremoniesFixture):
    def test_empty_produces_fails(self):
        data = dict(VALID, produces=[])
        self.write("standup.yaml", data)
        errors = self.validate()
        self.assertEqual(len(errors), 1)
        self.assertIn("produces", errors[0])
        self.assertIn("non-empty", errors[0])

    def test_empty_consumes_fails(self):
        data = dict(VALID, consumes=[])
        self.write("standup.yaml", data)
        errors = self.validate()
        self.assertEqual(len(errors), 1)
        self.assertIn("consumes", errors[0])

    def test_empty_escalates_when_fails(self):
        data = dict(VALID, escalates_when=[])
        self.write("standup.yaml", data)
        errors = self.validate()
        self.assertEqual(len(errors), 1)
        self.assertIn("escalates_when", errors[0])

    def test_non_list_produces_fails(self):
        data = dict(VALID, produces="a single string, not a list")
        self.write("standup.yaml", data)
        errors = self.validate()
        self.assertEqual(len(errors), 1)
        self.assertIn("produces", errors[0])


class TestYamlParseError(CeremoniesFixture):
    def test_invalid_yaml_is_reported_and_does_not_crash(self):
        (self.ceremonies / "broken.yaml").write_text("ceremony: [unterminated\n")
        errors = self.validate()
        self.assertEqual(len(errors), 1)
        self.assertIn("YAML parse error", errors[0])

    def test_a_non_mapping_document_fails(self):
        (self.ceremonies / "broken.yaml").write_text("- just\n- a\n- list\n")
        errors = self.validate()
        self.assertEqual(len(errors), 1)
        self.assertIn("mapping", errors[0])


class TestNoFilesFound(CeremoniesFixture):
    def test_empty_directory_is_reported_as_a_violation(self):
        errors = self.validate()
        self.assertEqual(len(errors), 1)
        self.assertIn("no ceremony declarations found", errors[0])


class TestAllViolationsCollected(CeremoniesFixture):
    """Not fail-fast: every problem in every file, in one run."""

    def test_two_bad_files_both_report(self):
        bad_one = dict(VALID)
        del bad_one["owner"]
        self.write("standup.yaml", bad_one)
        bad_two = dict(VALID, ceremony="retro", cadence="0 7 * * 1",
                       role="not-a-real-role")
        self.write("retro.yaml", bad_two)
        errors = self.validate()
        self.assertEqual(len(errors), 2)
        joined = " ".join(errors)
        self.assertIn("owner", joined)
        self.assertIn("not-a-real-role", joined)


class TestKnownRoles(unittest.TestCase):
    def test_known_roles_reads_directory_names(self):
        root = Path(tempfile.mkdtemp())
        try:
            (root / "devops").mkdir()
            (root / "qa").mkdir()
            (root / "not-a-dir.yaml").write_text("x")
            self.assertEqual(C.known_roles(root), {"devops", "qa"})
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_known_roles_missing_directory_is_empty(self):
        self.assertEqual(C.known_roles(Path("/no/such/directory")), set())


class TestRealDeclarations(unittest.TestCase):
    """Regression: the five declarations merged by #132 must pass as-is."""

    def test_the_five_merged_declarations_pass(self):
        errors = C.validate_all(REPO_ROOT / "ceremonies", REPO_ROOT / "role-packs")
        self.assertEqual(errors, [], f"real ceremonies/ has violations: {errors}")

    def test_all_five_files_are_present(self):
        files = sorted(p.name for p in (REPO_ROOT / "ceremonies").glob("*.yaml"))
        self.assertEqual(
            files,
            ["planning.yaml", "refinement.yaml", "retro.yaml", "review.yaml",
             "standup.yaml"],
        )


if __name__ == "__main__":
    unittest.main()
