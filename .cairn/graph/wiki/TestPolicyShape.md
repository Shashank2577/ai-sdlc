# TestPolicyShape

> 10 nodes

## Key Concepts

- **TestPolicyShape** (10 connections) — `scripts/test_gate_check.py`
- **._packs()** (3 connections) — `scripts/test_gate_check.py`
- **.test_no_pack_may_write_another_packs_directory()** (3 connections) — `scripts/test_gate_check.py`
- **.test_only_the_governance_owner_may_write_the_gate_policy()** (2 connections) — `scripts/test_gate_check.py`
- **.test_the_governance_owner_is_gated_critical_by_its_label_alone()** (2 connections) — `scripts/test_gate_check.py`
- **Consequences** (2 connections) — `adrs/0003-governance-owner-keeps-policies-not-other-role-packs.md`
- **.test_every_rule_has_a_name_and_a_reason()** (1 connections) — `scripts/test_gate_check.py`
- **.test_the_gate_has_an_owner_and_a_default()** (1 connections) — `scripts/test_gate_check.py`
- **.test_the_governance_owner_cannot_merge()** (1 connections) — `scripts/test_gate_check.py`
- **.test_the_policy_admits_its_own_limits()** (1 connections) — `scripts/test_gate_check.py`

## Relationships

- [test_gate_check.py](test_gate_check.py.md) (1 shared connections)
- [ADR-0004: The approval gate scopes to write capability, not to path mentions](ADR-0004-_The_approval_gate_scopes_to_write_capability,_not_to_path_mentions.md) (1 shared connections)
- [rules](rules.md) (1 shared connections)
- [ADR-0003: The governance owner keeps `policies/**` but not other roles' packs](ADR-0003-_The_governance_owner_keeps_`policies-__`_but_not_other_roles'_packs.md) (1 shared connections)

## Source Files

- `adrs/0003-governance-owner-keeps-policies-not-other-role-packs.md`
- `scripts/test_gate_check.py`

## Audit Trail

- EXTRACTED: 14 (93%)
- INFERRED: 1 (7%)
- AMBIGUOUS: 0 (0%)

---

*Part of the Cairn knowledge wiki. See [index](index.md) to navigate.*