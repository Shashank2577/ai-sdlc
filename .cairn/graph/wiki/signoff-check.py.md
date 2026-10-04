# signoff-check.py

> 17 nodes

## Key Concepts

- **signoff-check.py** (18 connections) — `scripts/signoff-check.py`
- **main()** (6 connections) — `scripts/signoff-check.py`
- **classify()** (4 connections) — `scripts/signoff-check.py`
- **fetch_label_events()** (4 connections) — `scripts/signoff-check.py`
- **fetch_issue_labels()** (3 connections) — `scripts/signoff-check.py`
- **gh()** (3 connections) — `scripts/signoff-check.py`
- **_last_actor_for_label()** (3 connections) — `scripts/signoff-check.py`
- **load_policy()** (3 connections) — `scripts/signoff-check.py`
- **validate_structure()** (3 connections) — `scripts/signoff-check.py`
- **_load_gate_check()** (2 connections) — `scripts/signoff-check.py`
- **_validate_scope()** (2 connections) — `scripts/signoff-check.py`
- **Path** (1 connections)
- **The actor of the most recent `labeled` event that applied `label`. None if the…** (1 connections) — `scripts/signoff-check.py`
- **(state, detail) for one item, given its current labels and label event history.…** (1 connections) — `scripts/signoff-check.py`
- **Validate policies/signoff.yaml, and classify one item's sign-off state. Two…** (1 connections) — `scripts/signoff-check.py`
- **Every `labeled` event on the issue: {label, actor, created_at}.** (1 connections) — `scripts/signoff-check.py`
- **`is_human()`, reused rather than reimplemented — the two scripts must never…** (1 connections) — `scripts/signoff-check.py`

## Relationships

- [pathlib](pathlib.md) (3 shared connections)
- [json](json.md) (2 shared connections)
- [argparse](argparse.md) (1 shared connections)
- [subprocess](subprocess.md) (1 shared connections)

## Source Files

- `scripts/signoff-check.py`

## Audit Trail

- EXTRACTED: 32 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the Cairn knowledge wiki. See [index](index.md) to navigate.*