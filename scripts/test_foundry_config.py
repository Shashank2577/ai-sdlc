#!/usr/bin/env python3
"""Tests for foundry.yaml (#324): the loader, and a guard that fails when a
new hard-coded owner literal lands in code instead of in the config.

    python3 scripts/test_foundry_config.py
"""

from __future__ import annotations

import builtins
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import foundry_config as C  # noqa: E402

# Files allowed to name the owner outright, each with its reason. Anything
# else that does is a default that should have read foundry.yaml.
ALLOWED = {
    "foundry.yaml": "the config itself",
    "policies/products.yaml": "the registry: each product's repo and board are data a human edits",
    "policies/environments.yaml": "prod's required reviewer is a named person, checked live by check-environments.py",
    ".github/CODEOWNERS": "GitHub reads literal handles only",
    # #290 (PR #326) replaces the hardcoded board with the registry; drop
    # these two once it merges.
    ".github/workflows/project-sync.yml": "removed by #290",
    "scripts/sync-project.py": "removed by #290",
}
# A citation names where something happened (owner/repo#123, an issue or
# run URL) or who did it (@handle, in evidence prose); history keeps the
# name it was written with.
CITATION = re.compile(r"[\w.-]+/[\w.-]+#\d+|/(issues|pull|actions/runs)/\d+|(?<![\w/.])@[A-Za-z][\w-]*")
CODE = ("*.py", "*.sh", "*.yml", "*.yaml")


def is_test(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name.startswith(("test_", "test-")) or "/tests/" in f"/{path}"


def offending_lines(owner: str) -> list[str]:
    files = subprocess.run(["git", "ls-files", *CODE], cwd=REPO_ROOT, capture_output=True,
                           text=True, check=True).stdout.split()
    out = []
    for path in files:
        if path in ALLOWED or is_test(path) or not (REPO_ROOT / path).is_file():
            continue
        for n, line in enumerate((REPO_ROOT / path).read_text(errors="ignore").splitlines(), 1):
            if owner.lower() not in line.lower():
                continue
            if line.lstrip().startswith("#") or CITATION.search(line):
                continue
            out.append(f"{path}:{n}: {line.strip()}")
    return out


class TestLoader(unittest.TestCase):
    def setUp(self):
        C.load.cache_clear()

    def tearDown(self):
        C.load.cache_clear()

    def test_reads_the_checked_in_config(self):
        self.assertRegex(C.control_plane(), r"^[\w.-]+/[\w.-]+$")
        self.assertEqual(C.repo_url(), f"https://github.com/{C.control_plane()}")
        self.assertTrue(C.pages_url().startswith(f"https://{C.owner().lower()}.github.io/"))

    def test_environment_overrides_the_repo(self):
        with mock.patch.dict(os.environ, {"FOUNDRY_CONTROL_PLANE": "acme/plane"}):
            self.assertEqual(C.control_plane(), "acme/plane")
            self.assertEqual(C.board_url(4), "https://github.com/users/acme/projects/4")

    def test_parses_without_pyyaml(self):
        real_import = builtins.__import__

        def no_yaml(name, *a, **k):
            if name == "yaml":
                raise ImportError
            return real_import(name, *a, **k)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "foundry.yaml"
            p.write_text("version: 0\ncontrol_plane:\n  repo: acme/plane\n  product: plane\n  owner_kind: orgs\n")
            with mock.patch.object(builtins, "__import__", no_yaml):
                self.assertEqual(C.load(p), {"repo": "acme/plane", "product": "plane", "owner_kind": "orgs"})

    def test_rejects_a_repo_without_an_owner(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "foundry.yaml"
            p.write_text("control_plane:\n  repo: plane\n")
            with self.assertRaises(SystemExit):
                C.load(p)


class TestNoHardcodedOwner(unittest.TestCase):
    def test_code_reads_the_owner_from_foundry_yaml(self):
        C.load.cache_clear()
        found = offending_lines(C.load()["repo"].split("/")[0])
        self.assertEqual(found, [], "hard-coded owner outside foundry.yaml — read foundry_config "
                                    "instead, or add the file to ALLOWED with its reason:\n" + "\n".join(found))

    def test_the_guard_catches_a_new_literal(self):
        self.assertTrue(CITATION.search("Work-Item: acme/plane#12"))
        self.assertTrue(CITATION.search("waiting on @acme's approval"))
        self.assertFalse(CITATION.search("uses: acme/plane/.github/workflows/x.yml@main"))
        self.assertFalse(CITATION.search('ap.add_argument("--repo", default="acme/plane")'))


if __name__ == "__main__":
    unittest.main(verbosity=1)
