# GitNotesStore

> 17 nodes

## Key Concepts

- **GitNotesStore** (14 connections) — `adapters/memory/git_notes/store.py`
- **Note** (8 connections) — `adapters/memory/base.py`
- **._git()** (7 connections) — `adapters/memory/git_notes/store.py`
- **.read_by_commit()** (5 connections) — `adapters/memory/git_notes/store.py`
- **.search()** (5 connections) — `adapters/memory/git_notes/store.py`
- **.read_by_path()** (4 connections) — `adapters/memory/git_notes/store.py`
- **.write()** (4 connections) — `adapters/memory/git_notes/store.py`
- **.read_by_path()** (3 connections) — `adapters/memory/base.py`
- **.search()** (3 connections) — `adapters/memory/base.py`
- **._format()** (2 connections) — `adapters/memory/git_notes/store.py`
- **.__init__()** (1 connections) — `adapters/memory/git_notes/store.py`
- **CompletedProcess** (1 connections)
- **Return the notes for every commit touching `path` that has one, most recent…** (1 connections) — `adapters/memory/base.py`
- **Return the notes whose body contains `query`, case-insensitively. (`memory.py…** (1 connections) — `adapters/memory/base.py`
- **`-f` is deliberate: a session that revisits a commit (rare, but the…** (1 connections) — `adapters/memory/git_notes/store.py`
- **`git notes show` exits 1 for "no note found" — that is absence, not an error,…** (1 connections) — `adapters/memory/git_notes/store.py`
- **`git notes list` on a ref that has never been written to still exits 0 with…** (1 connections) — `adapters/memory/git_notes/store.py`

## Relationships

- [subprocess](subprocess.md) (9 shared connections)
- [_run](_run.md) (2 shared connections)
- [pathlib](pathlib.md) (1 shared connections)

## Source Files

- `adapters/memory/base.py`
- `adapters/memory/git_notes/store.py`

## Audit Trail

- EXTRACTED: 36 (97%)
- INFERRED: 1 (3%)
- AMBIGUOUS: 0 (0%)

---

*Part of the Cairn knowledge wiki. See [index](index.md) to navigate.*