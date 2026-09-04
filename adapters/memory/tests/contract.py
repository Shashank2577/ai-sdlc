"""The one contract, run against every MemoryStore implementation (P3-5
acceptance criteria).

`MemoryStoreContractTests` is a plain mixin, not a `unittest.TestCase` —
deliberate, so importing this module never collects it as a runnable test
on its own; only `test_git_notes.py`, which mixes it with
`unittest.TestCase`, does.

Each concrete subclass must implement `make_store()` (a fresh, empty store)
and `commit(filename, content, message)` (creates a real commit in the
backing repo and returns its identifier — `MemoryStore` addresses notes by
commit, so the fixture needs real commits to attach them to, not fakes).
"""

from __future__ import annotations

from adapters.memory.base import MemoryStore


class MemoryStoreContractTests:
    def make_store(self) -> MemoryStore:
        raise NotImplementedError

    def commit(self, filename: str, content: str, message: str) -> str:
        raise NotImplementedError

    def setUp(self):
        super().setUp()
        self.store = self.make_store()

    # --- write / read_by_commit --------------------------------------------

    def test_read_by_commit_returns_the_note_that_was_written(self):
        sha = self.commit("a.txt", "hello", "add a")
        self.store.write(sha, work_item="x#1", tried="tried A first", gotcha="A doesn't work")
        note = self.store.read_by_commit(sha)
        self.assertIsNotNone(note)
        self.assertIn("Work-Item: x#1", note)
        self.assertIn("Gotcha: A doesn't work", note)

    def test_write_includes_requirement_when_given(self):
        sha = self.commit("a.txt", "hello", "add a")
        self.store.write(sha, work_item="x#1", tried="t", gotcha="g", requirement="REQ-013")
        note = self.store.read_by_commit(sha)
        self.assertIn("Requirement: REQ-013", note)

    def test_write_omits_requirement_line_when_not_given(self):
        sha = self.commit("a.txt", "hello", "add a")
        self.store.write(sha, work_item="x#1", tried="t", gotcha="g")
        note = self.store.read_by_commit(sha)
        self.assertNotIn("Requirement:", note)

    def test_read_by_commit_on_a_commit_with_no_note_returns_none(self):
        sha = self.commit("a.txt", "hello", "add a")
        self.assertIsNone(self.store.read_by_commit(sha))

    def test_write_overwrites_a_prior_note_on_the_same_commit(self):
        sha = self.commit("a.txt", "hello", "add a")
        self.store.write(sha, work_item="x#1", tried="first attempt", gotcha="g1")
        self.store.write(sha, work_item="x#1", tried="second attempt", gotcha="g2")
        note = self.store.read_by_commit(sha)
        self.assertIn("second attempt", note)
        self.assertNotIn("first attempt", note)

    # --- read_by_path --------------------------------------------------------

    def test_read_by_path_returns_notes_for_commits_touching_that_file(self):
        sha_a = self.commit("a.txt", "hello", "add a")
        sha_b = self.commit("b.txt", "world", "add b")
        self.store.write(sha_a, work_item="x#1", tried="t-a", gotcha="g-a")
        self.store.write(sha_b, work_item="x#1", tried="t-b", gotcha="g-b")

        notes_a = self.store.read_by_path("a.txt")
        self.assertEqual([n.commit for n in notes_a], [sha_a])
        self.assertIn("g-a", notes_a[0].body)

        notes_b = self.store.read_by_path("b.txt")
        self.assertEqual([n.commit for n in notes_b], [sha_b])

    def test_read_by_path_with_no_note_returns_empty_list(self):
        self.commit("a.txt", "hello", "add a")
        self.assertEqual(self.store.read_by_path("a.txt"), [])

    # --- search -----------------------------------------------------------------

    def test_search_on_an_empty_store_returns_nothing(self):
        self.commit("a.txt", "hello", "add a")
        self.assertEqual(self.store.search("anything"), [])

    def test_search_finds_a_note_by_substring_case_insensitively(self):
        sha1 = self.commit("a.txt", "hello", "add a")
        sha2 = self.commit("b.txt", "world", "add b")
        self.store.write(sha1, work_item="x#1", tried="t1", gotcha="the PAT scope was too narrow")
        self.store.write(sha2, work_item="x#1", tried="t2", gotcha="unrelated finding")

        matches = self.store.search("pat scope")
        self.assertEqual([n.commit for n in matches], [sha1])

    def test_search_matches_nothing_for_an_absent_term(self):
        sha = self.commit("a.txt", "hello", "add a")
        self.store.write(sha, work_item="x#1", tried="t", gotcha="g")
        self.assertEqual(self.store.search("nonexistent-term-xyz"), [])

    def test_search_matches_on_the_work_item_line(self):
        """Mirrors dispatch.yml's session-start lookup: `search` on a
        `Work-Item: <owner>/<repo>#<issue>` substring."""
        sha = self.commit("a.txt", "hello", "add a")
        self.store.write(sha, work_item="Shashank2577/foundry-program#158", tried="t", gotcha="g")
        matches = self.store.search("Work-Item: Shashank2577/foundry-program#158")
        self.assertEqual([n.commit for n in matches], [sha])
