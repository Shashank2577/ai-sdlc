"""Runs the shared contract suite against GitNotesStore, against a real
temporary git repository — not a mock. The same reasoning
`scripts/test_memory.py` documents applies here: whether `git notes show`
really exits non-zero for a missing note is a fact about git, not something
a stub should assert on its own.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from adapters.memory.git_notes import GitNotesStore
from adapters.memory.tests.contract import MemoryStoreContractTests

REPO_ROOT = Path(__file__).resolve().parents[3]
MEMORY_CLI = REPO_ROOT / "scripts" / "memory.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"git {args} failed: {result.stderr}")
    return result


class TestGitNotesStoreContract(MemoryStoreContractTests, unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        _run(["init", "-q", str(self.repo)], cwd=self.repo)
        _run(["config", "user.email", "test@example.com"], cwd=self.repo)
        _run(["config", "user.name", "test"], cwd=self.repo)
        super().setUp()

    def tearDown(self):
        self.tmp.cleanup()

    def make_store(self):
        return GitNotesStore(repo=str(self.repo))

    def commit(self, filename: str, content: str, message: str) -> str:
        (self.repo / filename).write_text(content)
        _run(["add", filename], cwd=self.repo)
        _run(["commit", "-q", "-m", message], cwd=self.repo)
        return _run(["rev-parse", "HEAD"], cwd=self.repo).stdout.strip()


class TestReadableThroughTheExistingCLI(unittest.TestCase):
    """P3-5's acceptance criteria: a note written through the seam reads
    back identically through `scripts/memory.py`'s existing, unmodified
    CLI — proving the seam is a faithful stand-in, not a divergent copy."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        _run(["init", "-q", str(self.repo)], cwd=self.repo)
        _run(["config", "user.email", "test@example.com"], cwd=self.repo)
        _run(["config", "user.name", "test"], cwd=self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def test_note_written_via_the_seam_is_read_back_identically_by_the_cli(self):
        (self.repo / "a.txt").write_text("hello")
        _run(["add", "a.txt"], cwd=self.repo)
        _run(["commit", "-q", "-m", "add a"], cwd=self.repo)
        sha = _run(["rev-parse", "HEAD"], cwd=self.repo).stdout.strip()

        store = GitNotesStore(repo=str(self.repo))
        written = store.write(
            sha,
            work_item="Shashank2577/foundry-program#158",
            tried="wired the seam under scripts/memory.py",
            gotcha="the CLI and the seam must produce byte-identical notes",
        )

        result = subprocess.run(
            [sys.executable, str(MEMORY_CLI), "--repo", str(self.repo), "read", "--commit", sha],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, written)


if __name__ == "__main__":
    unittest.main(verbosity=2)
