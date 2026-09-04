"""Git-notes implementation of the memory seam.

This is `scripts/memory.py`'s `write_note`/`read_note`/`read_path`/
`search_notes` — the `refs/notes/foundry` behaviour built for #119 — moved
behind `adapters.memory.base.MemoryStore` with no change in behaviour.
`scripts/memory.py` still calls `git notes` directly today (this story
introduces the seam; it does not rewire that module — see the PR), so the
git invocations below are a parallel implementation of the same contract,
not a wrapper around `scripts/memory.py`'s functions.

Notes live on `refs/notes/foundry`, not git's default `refs/notes/commits`,
so every git-notes invocation passes `--ref` explicitly rather than relying
on git's default — the same gotcha `scripts/memory.py` documents.
"""

from __future__ import annotations

import subprocess

from ..base import DEFAULT_REF, MemoryStore, Note


class GitError(RuntimeError):
    """A git invocation failed for a reason other than 'note not found'."""


class GitNotesStore(MemoryStore):
    def __init__(self, *, repo: str | None = None):
        self._repo = repo

    def _git(self, args: list[str], check: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run(
            ["git", *args],
            cwd=self._repo,
            capture_output=True,
            text=True,
        )
        if check and result.returncode != 0:
            raise GitError(result.stderr.strip() or f"git {' '.join(args)} failed")
        return result

    @staticmethod
    def _format(work_item: str, tried: str, gotcha: str, requirement: str | None) -> str:
        lines = [f"Work-Item: {work_item}"]
        if requirement:
            lines.append(f"Requirement: {requirement}")
        lines.append(f"Tried: {tried}")
        lines.append(f"Gotcha: {gotcha}")
        return "\n".join(lines) + "\n"

    def write(
        self,
        commit: str,
        *,
        work_item: str,
        tried: str,
        gotcha: str,
        requirement: str | None = None,
        ref: str = DEFAULT_REF,
    ) -> str:
        """`-f` is deliberate: a session that revisits a commit (rare, but
        the dispatcher's session-end step could retry) replaces the note
        rather than failing with "a note already exists"."""
        body = self._format(work_item, tried, gotcha, requirement)
        self._git(["notes", f"--ref={ref}", "add", "-f", "-m", body, commit])
        return body

    def read_by_commit(self, commit: str, *, ref: str = DEFAULT_REF) -> str | None:
        """`git notes show` exits 1 for "no note found" — that is absence,
        not an error, so it is swallowed here rather than raised."""
        result = self._git(["notes", f"--ref={ref}", "show", commit], check=False)
        if result.returncode != 0:
            return None
        return result.stdout

    def read_by_path(self, path: str, *, ref: str = DEFAULT_REF) -> list[Note]:
        log = self._git(["log", "--format=%H", "--", path], check=False)
        notes = []
        for commit in log.stdout.split():
            body = self.read_by_commit(commit, ref=ref)
            if body is not None:
                notes.append(Note(commit=commit, body=body))
        return notes

    def search(self, query: str, *, ref: str = DEFAULT_REF) -> list[Note]:
        """`git notes list` on a ref that has never been written to still
        exits 0 with empty output — verified against a real repo, not
        assumed — so an empty notes tree needs no special-casing here."""
        result = self._git(["notes", f"--ref={ref}", "list"], check=False)
        matches = []
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) != 2:
                continue
            _note_blob, commit = parts
            body = self.read_by_commit(commit, ref=ref)
            if body and query.lower() in body.lower():
                matches.append(Note(commit=commit, body=body))
        return matches
