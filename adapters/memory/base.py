"""The memory seam (P3-5 / REQ-013).

This is not a general note-storage API. Every method here exists because
`scripts/memory.py` exposes it today, or `.github/workflows/dispatch.yml`
calls it. See the PR for the call-site list:

- `write` — `scripts/memory.py`'s `write_note`/`_cmd_write` (the `write`
  subcommand), and `dispatch.yml`'s session-end step, which shells out to
  `python3 scripts/memory.py write "$note_commit" --work-item ... --tried
  ... --gotcha ...` before pushing `refs/notes/foundry`.
- `read_by_commit` — `write_note`/`_cmd_read`'s `--commit` branch (the
  `read --commit` subcommand). No caller in `dispatch.yml` today.
- `read_by_path` — `read_path`/`_cmd_read`'s `--path` branch (the `read
  --path` subcommand). No caller in `dispatch.yml` today.
- `search` — `search_notes`/`_cmd_search` (the `search` subcommand), and
  `dispatch.yml`'s session-start step, which shells out to `python3
  scripts/memory.py search "Work-Item: ${GITHUB_REPOSITORY}#${ISSUE}"` to
  fold prior sessions' notes on this exact work item into the prompt.

Adding a method with no caller is scope creep on this interface, not
"completeness".

One implementation satisfies this contract today: `adapters/memory/git_notes/`
(the existing `refs/notes/foundry` behaviour, moved behind the seam). A
Seal/MCP-backed second implementation is out of scope — PRD §12 and
`requirements/coverage.yaml`'s own note for REQ-013 both place it in a later
phase, and there are no credentials or a known client API to build one
against yet. Exercised by the single shared suite in
`adapters/memory/tests/contract.py`.

`scripts/memory.py` is not rewired to call through this seam in this story —
it keeps calling `git notes` directly, same as `sync-project.py`/`assign.py`
kept calling `gh` directly when the tracker seam (#135) was introduced. This
story proves the seam's behaviour matches, not that every caller has been
migrated onto it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

DEFAULT_REF = "refs/notes/foundry"


@dataclass(frozen=True)
class Note:
    commit: str
    body: str


class MemoryStore(ABC):
    """The operations `scripts/memory.py` and `dispatch.yml` call.

    Every abstract method below maps to one subcommand of `memory.py`
    today. Nothing here is speculative.
    """

    @abstractmethod
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
        """Attach a note to `commit`, overwriting any prior note on it.
        Returns the note body that was written. (`memory.py write`;
        `dispatch.yml`'s session-end step.)"""

    @abstractmethod
    def read_by_commit(self, commit: str, *, ref: str = DEFAULT_REF) -> str | None:
        """Return the note body for `commit`, or `None` if it has none.
        (`memory.py read --commit`.)"""

    @abstractmethod
    def read_by_path(self, path: str, *, ref: str = DEFAULT_REF) -> list[Note]:
        """Return the notes for every commit touching `path` that has one,
        most recent first. (`memory.py read --path`.)"""

    @abstractmethod
    def search(self, query: str, *, ref: str = DEFAULT_REF) -> list[Note]:
        """Return the notes whose body contains `query`, case-insensitively.
        (`memory.py search`; `dispatch.yml`'s session-start step, matching on
        a note's `Work-Item:` line.)"""
