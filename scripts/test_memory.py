#!/usr/bin/env python3
"""Tests for scripts/memory.py — the engineering-memory git notes store.

These run against real temporary git repositories, not mocks: the
acceptance criteria for #119 are about actual git-notes behavior (does
`show` really exit non-zero for a missing note, does a custom notes ref
really survive a push and a fetch into a fresh clone), and those are
exactly the things a mock would assume rather than prove.

    python3 scripts/test_memory.py
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("memory", HERE / "memory.py")
M = importlib.util.module_from_spec(spec)
sys.modules["memory"] = M
spec.loader.exec_module(M)


def run(args, cwd=None, check=True):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"git {args} failed: {result.stderr}")
    return result


def init_repo(path: Path) -> None:
    run(["init", "-q", str(path)])
    run(["config", "user.email", "test@example.com"], cwd=path)
    run(["config", "user.name", "test"], cwd=path)


def commit(path: Path, filename: str, content: str, message: str) -> str:
    (path / filename).write_text(content)
    run(["add", filename], cwd=path)
    run(["commit", "-q", "-m", message], cwd=path)
    return run(["rev-parse", "HEAD"], cwd=path).stdout.strip()


class TestWriteReadRoundtrip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        init_repo(self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_returns_the_note_that_was_written(self):
        sha = commit(self.repo, "a.txt", "hello", "add a")
        M.write_note(
            sha,
            work_item="Shashank2577/foundry-program#119",
            tried="tried adding notes on refs/notes/commits first",
            gotcha="the default ref isn't fetched by a plain `git fetch`",
            repo=str(self.repo),
        )
        note = M.read_note(sha, repo=str(self.repo))
        self.assertIsNotNone(note)
        self.assertIn("Work-Item: Shashank2577/foundry-program#119", note)
        self.assertIn("Gotcha: the default ref isn't fetched", note)

    def test_write_uses_the_foundry_ref_not_the_default(self):
        sha = commit(self.repo, "a.txt", "hello", "add a")
        M.write_note(sha, work_item="x#1", tried="t", gotcha="g", repo=str(self.repo))
        # nothing on git's default notes ref
        default = run(["notes", "show", sha], cwd=self.repo, check=False)
        self.assertNotEqual(default.returncode, 0)
        # something on refs/notes/foundry
        foundry = run(["notes", "--ref=refs/notes/foundry", "show", sha], cwd=self.repo, check=False)
        self.assertEqual(foundry.returncode, 0)

    def test_read_on_missing_note_returns_none_and_cli_exits_zero(self):
        sha = commit(self.repo, "a.txt", "hello", "add a")
        self.assertIsNone(M.read_note(sha, repo=str(self.repo)))

        result = subprocess.run(
            [sys.executable, str(HERE / "memory.py"), "--repo", str(self.repo), "read", "--commit", sha],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_write_overwrites_a_prior_note_on_the_same_commit(self):
        sha = commit(self.repo, "a.txt", "hello", "add a")
        M.write_note(sha, work_item="x#1", tried="first attempt", gotcha="g1", repo=str(self.repo))
        M.write_note(sha, work_item="x#1", tried="second attempt", gotcha="g2", repo=str(self.repo))
        note = M.read_note(sha, repo=str(self.repo))
        self.assertIn("second attempt", note)
        self.assertNotIn("first attempt", note)

    def test_read_by_path_returns_notes_for_commits_touching_that_file(self):
        sha_a = commit(self.repo, "a.txt", "hello", "add a")
        sha_b = commit(self.repo, "b.txt", "world", "add b")
        M.write_note(sha_a, work_item="x#1", tried="t-a", gotcha="g-a", repo=str(self.repo))
        M.write_note(sha_b, work_item="x#1", tried="t-b", gotcha="g-b", repo=str(self.repo))

        notes_a = M.read_path("a.txt", repo=str(self.repo))
        self.assertEqual([c for c, _ in notes_a], [sha_a])
        self.assertIn("g-a", notes_a[0][1])

        notes_b = M.read_path("b.txt", repo=str(self.repo))
        self.assertEqual([c for c, _ in notes_b], [sha_b])

    def test_read_by_path_with_no_note_returns_empty_list(self):
        commit(self.repo, "a.txt", "hello", "add a")
        self.assertEqual(M.read_path("a.txt", repo=str(self.repo)), [])


class TestSearch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        init_repo(self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def test_search_on_empty_notes_tree_returns_nothing_and_exits_zero(self):
        commit(self.repo, "a.txt", "hello", "add a")
        self.assertEqual(M.search_notes("anything", repo=str(self.repo)), [])

        result = subprocess.run(
            [sys.executable, str(HERE / "memory.py"), "--repo", str(self.repo), "search", "anything"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_search_finds_a_gotcha_by_substring_case_insensitively(self):
        sha1 = commit(self.repo, "a.txt", "hello", "add a")
        sha2 = commit(self.repo, "b.txt", "world", "add b")
        M.write_note(sha1, work_item="x#1", tried="t1", gotcha="the PAT scope was too narrow", repo=str(self.repo))
        M.write_note(sha2, work_item="x#1", tried="t2", gotcha="unrelated finding", repo=str(self.repo))

        matches = M.search_notes("pat scope", repo=str(self.repo))
        self.assertEqual([c for c, _ in matches], [sha1])

    def test_search_matches_nothing_for_an_absent_term(self):
        sha = commit(self.repo, "a.txt", "hello", "add a")
        M.write_note(sha, work_item="x#1", tried="t", gotcha="g", repo=str(self.repo))
        self.assertEqual(M.search_notes("nonexistent-term-xyz", repo=str(self.repo)), [])


class TestCustomRefPushFetch(unittest.TestCase):
    """#119's contract: verify push and fetch of refs/notes/foundry in a
    real temp clone before anything downstream relies on it — a custom
    notes ref is not fetched by a bare `git fetch` or `git clone`, only
    a plain commit-notes ref is fetched by default."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.origin = self.root / "origin.git"
        self.work = self.root / "work"
        run(["init", "-q", "--bare", str(self.origin)])
        run(["clone", "-q", str(self.origin), str(self.work)])
        run(["config", "user.email", "test@example.com"], cwd=self.work)
        run(["config", "user.name", "test"], cwd=self.work)

    def tearDown(self):
        self.tmp.cleanup()

    def test_note_on_custom_ref_survives_push_and_fetch_into_a_fresh_clone(self):
        sha = commit(self.work, "a.txt", "hello", "add a")
        run(["push", "-q", "origin", "HEAD:main"], cwd=self.work)

        M.write_note(sha, work_item="x#1", tried="t", gotcha="the ref needs an explicit fetch", repo=str(self.work))
        run(["push", "-q", "origin", "refs/notes/foundry"], cwd=self.work)

        fresh = self.root / "fresh"
        run(["clone", "-q", str(self.origin), str(fresh)])

        # A plain clone does not bring the custom notes ref along.
        self.assertIsNone(M.read_note(sha, repo=str(fresh)))

        run(["fetch", "-q", "origin", "refs/notes/foundry:refs/notes/foundry"], cwd=fresh)

        note = M.read_note(sha, repo=str(fresh))
        self.assertIsNotNone(note)
        self.assertIn("the ref needs an explicit fetch", note)

    def test_default_notes_ref_is_not_what_gets_pushed(self):
        sha = commit(self.work, "a.txt", "hello", "add a")
        run(["push", "-q", "origin", "HEAD:main"], cwd=self.work)
        M.write_note(sha, work_item="x#1", tried="t", gotcha="g", repo=str(self.work))

        result = run(["push", "origin", "refs/notes/commits"], cwd=self.work, check=False)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
