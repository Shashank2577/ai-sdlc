# ADR-0004: The approval gate scopes to write capability, not to path mentions

> 11 nodes

## Key Concepts

- **ADR-0004: The approval gate scopes to write capability, not to path mentions** (6 connections) — `adrs/0004-approval-gate-scopes-to-write-capability.md`
- **Consequences** (3 connections) — `adrs/0004-approval-gate-scopes-to-write-capability.md`
- **Options considered** (3 connections) — `adrs/0004-approval-gate-scopes-to-write-capability.md`
- **.test_a_pack_cannot_reach_its_own_gate_through_write_capability()** (2 connections) — `scripts/test_gate_check.py`
- **.test_every_guarded_path_names_a_real_scope_pattern()** (2 connections) — `scripts/test_gate_check.py`
- **0004-approval-gate-scopes-to-write-capability.md** (1 connections) — `adrs/0004-approval-gate-scopes-to-write-capability.md`
- **Context** (1 connections) — `adrs/0004-approval-gate-scopes-to-write-capability.md`
- **Decision** (1 connections) — `adrs/0004-approval-gate-scopes-to-write-capability.md`
- **Option A: Keep text/substring matching on protected path names** (1 connections) — `adrs/0004-approval-gate-scopes-to-write-capability.md`
- **Option B: Scope each `guards_paths` rule to fire only when the story's role could actually write one of those paths, per that role's own `write_scope`** (1 connections) — `adrs/0004-approval-gate-scopes-to-write-capability.md`
- **Recommendation** (1 connections) — `adrs/0004-approval-gate-scopes-to-write-capability.md`

## Relationships

- [TestPolicyShape](TestPolicyShape.md) (1 shared connections)
- [rules](rules.md) (1 shared connections)

## Source Files

- `adrs/0004-approval-gate-scopes-to-write-capability.md`
- `scripts/test_gate_check.py`

## Audit Trail

- EXTRACTED: 10 (83%)
- INFERRED: 2 (17%)
- AMBIGUOUS: 0 (0%)

---

*Part of the Cairn knowledge wiki. See [index](index.md) to navigate.*