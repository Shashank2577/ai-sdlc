# gate-check.py

> 30 nodes

## Key Concepts

- **gate-check.py** (20 connections) — `scripts/gate-check.py`
- **main()** (7 connections) — `scripts/gate-check.py`
- **matched_rules()** (6 connections) — `scripts/gate-check.py`
- **ADR-0007: Approval is proven by the identity of who applied the label, never by the label's presence** (6 connections) — `adrs/0007-approval-proven-by-labeler-identity-not-label-presence.md`
- **is_human()** (5 connections) — `scripts/gate-check.py`
- **role_can_write()** (5 connections) — `scripts/gate-check.py`
- **_covers()** (4 connections) — `scripts/gate-check.py`
- **gh()** (3 connections) — `scripts/gate-check.py`
- **load_gate()** (3 connections) — `scripts/gate-check.py`
- **_pattern()** (3 connections) — `scripts/gate-check.py`
- **read_issue()** (3 connections) — `scripts/gate-check.py`
- **_root()** (3 connections) — `scripts/gate-check.py`
- **Options considered** (3 connections) — `adrs/0007-approval-proven-by-labeler-identity-not-label-presence.md`
- **render_held()** (2 connections) — `scripts/gate-check.py`
- **role_of_labels()** (2 connections) — `scripts/gate-check.py`
- **Path** (2 connections)
- **Decision** (2 connections) — `adrs/0007-approval-proven-by-labeler-identity-not-label-presence.md`
- **Option B: Enforce via the `issues: labeled` event payload's sender — dispatch proceeds only when a human account applied the label; an agent-applied label on a critical rule reverts the story and posts `needs-human`** (2 connections) — `adrs/0007-approval-proven-by-labeler-identity-not-label-presence.md`
- **0007-approval-proven-by-labeler-identity-not-label-presence.md** (1 connections) — `adrs/0007-approval-proven-by-labeler-identity-not-label-presence.md`
- **Consequences** (1 connections) — `adrs/0007-approval-proven-by-labeler-identity-not-label-presence.md`
- **Context** (1 connections) — `adrs/0007-approval-proven-by-labeler-identity-not-label-presence.md`
- **Option A: Treat `status:ready` as approval whenever present, regardless of who applied it** (1 connections) — `adrs/0007-approval-proven-by-labeler-identity-not-label-presence.md`
- **Recommendation** (1 connections) — `adrs/0007-approval-proven-by-labeler-identity-not-label-presence.md`
- **Could `role` write any of `guarded`, per its own pack policy? Deny wins over…** (1 connections) — `scripts/gate-check.py`
- **Every critical rule this story trips. Empty means routine. Returns all matches…** (1 connections) — `scripts/gate-check.py`
- *... and 5 more nodes in this community*

## Relationships

- [json](json.md) (2 shared connections)
- [pathlib](pathlib.md) (2 shared connections)
- [argparse](argparse.md) (1 shared connections)
- [check-story-scope.py](check-story-scope.py.md) (1 shared connections)
- [subprocess](subprocess.md) (1 shared connections)

## Source Files

- `adrs/0007-approval-proven-by-labeler-identity-not-label-presence.md`
- `scripts/gate-check.py`

## Audit Trail

- EXTRACTED: 48 (96%)
- INFERRED: 2 (4%)
- AMBIGUOUS: 0 (0%)

---

*Part of the Cairn knowledge wiki. See [index](index.md) to navigate.*