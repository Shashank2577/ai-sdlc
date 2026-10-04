# subprocess

> 20 nodes

## Key Concepts

- **subprocess** (26 connections)
- **MemoryStore** (13 connections) — `adapters/memory/base.py`
- **memory/base.py** (8 connections) — `adapters/memory/base.py`
- **store.py** (8 connections) — `adapters/memory/git_notes/store.py`
- **dataclasses** (6 connections)
- **GitError** (5 connections) — `adapters/memory/git_notes/store.py`
- **memory/tests/contract.py** (5 connections) — `adapters/memory/tests/contract.py`
- **git_notes/__init__.py** (4 connections) — `adapters/memory/git_notes/__init__.py`
- **memory/__init__.py** (3 connections) — `adapters/memory/__init__.py`
- **.read_by_commit()** (2 connections) — `adapters/memory/base.py`
- **.write()** (2 connections) — `adapters/memory/base.py`
- **ABC** (2 connections)
- **RuntimeError** (1 connections)
- **The memory seam (P3-5 / REQ-013). This is not a general note-storage API. Every…** (1 connections) — `adapters/memory/base.py`
- **The operations `scripts/memory.py` and `dispatch.yml` call. Every abstract…** (1 connections) — `adapters/memory/base.py`
- **Attach a note to `commit`, overwriting any prior note on it. Returns the note…** (1 connections) — `adapters/memory/base.py`
- **Return the note body for `commit`, or `None` if it has none. (`memory.py read…** (1 connections) — `adapters/memory/base.py`
- **Git-notes implementation of the memory seam. This is `scripts/memory.py`'s…** (1 connections) — `adapters/memory/git_notes/store.py`
- **A git invocation failed for a reason other than 'note not found'.** (1 connections) — `adapters/memory/git_notes/store.py`
- **The one contract, run against every MemoryStore implementation (P3-5 acceptance…** (1 connections) — `adapters/memory/tests/contract.py`

## Relationships

- [GitNotesStore](GitNotesStore.md) (9 shared connections)
- [MemoryStoreContractTests](MemoryStoreContractTests.md) (3 shared connections)
- [pathlib](pathlib.md) (3 shared connections)
- [check-story-scope.py](check-story-scope.py.md) (3 shared connections)
- [json](json.md) (2 shared connections)
- [dashboards/build.py](dashboards-build.py.md) (2 shared connections)
- [portal/build.py](portal-build.py.md) (2 shared connections)
- [adr.py](adr.py.md) (1 shared connections)
- [transcript-to-prd.py](transcript-to-prd.py.md) (1 shared connections)
- [burndown.py](burndown.py.md) (1 shared connections)
- [decisions.py](decisions.py.md) (1 shared connections)
- [qa.py](qa.py.md) (1 shared connections)

## Source Files

- `adapters/memory/__init__.py`
- `adapters/memory/base.py`
- `adapters/memory/git_notes/__init__.py`
- `adapters/memory/git_notes/store.py`
- `adapters/memory/tests/contract.py`

## Audit Trail

- EXTRACTED: 67 (99%)
- INFERRED: 1 (1%)
- AMBIGUOUS: 0 (0%)

---

*Part of the Cairn knowledge wiki. See [index](index.md) to navigate.*