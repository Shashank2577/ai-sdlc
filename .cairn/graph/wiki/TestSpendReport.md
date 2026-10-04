# TestSpendReport

> 53 nodes

## Key Concepts

- **TestSpendReport** (25 connections) — `scripts/test_budgets.py`
- **.write()** (16 connections) — `scripts/test_budgets.py`
- **test_budgets.py** (14 connections) — `scripts/test_budgets.py`
- **PackFixture** (12 connections) — `scripts/test_budgets.py`
- **execution()** (12 connections) — `scripts/test_budgets.py`
- **TestBudgetResolution** (9 connections) — `scripts/test_budgets.py`
- **TestFallbackParser** (9 connections) — `scripts/test_budgets.py`
- **.test_a_session_with_no_reported_cost_does_not_breach_on_cost()** (3 connections) — `scripts/test_budgets.py`
- **.test_cache_reads_are_excluded_from_the_tripwire()** (3 connections) — `scripts/test_budgets.py`
- **.test_cost_over_the_ceiling_is_a_breach()** (3 connections) — `scripts/test_budgets.py`
- **.test_inside_budget()** (3 connections) — `scripts/test_budgets.py`
- **.test_no_denials_adds_no_noise()** (3 connections) — `scripts/test_budgets.py`
- **.test_permission_denials_are_surfaced()** (3 connections) — `scripts/test_budgets.py`
- **.test_rendered_table_distinguishes_a_breach_from_a_tripwire()** (3 connections) — `scripts/test_budgets.py`
- **.test_several_enforced_lines_can_breach_at_once()** (3 connections) — `scripts/test_budgets.py`
- **.test_tokens_over_the_line_are_a_tripwire_not_a_breach()** (3 connections) — `scripts/test_budgets.py`
- **.test_totals_include_cache_tokens()** (3 connections) — `scripts/test_budgets.py`
- **.test_wall_clock_breach_is_detected()** (3 connections) — `scripts/test_budgets.py`
- **.test_a_non_numeric_budget_is_refused()** (2 connections) — `scripts/test_budgets.py`
- **.test_a_policy_key_the_dispatcher_does_not_know_is_ignored()** (2 connections) — `scripts/test_budgets.py`
- **.test_a_zero_cost_ceiling_is_refused()** (2 connections) — `scripts/test_budgets.py`
- **.test_missing_pack_falls_back_to_defaults_not_to_nothing()** (2 connections) — `scripts/test_budgets.py`
- **.test_override_wins_over_policy()** (2 connections) — `scripts/test_budgets.py`
- **.test_policy_wins_over_defaults()** (2 connections) — `scripts/test_budgets.py`
- **.test_zero_override_means_use_the_policy()** (2 connections) — `scripts/test_budgets.py`
- *... and 28 more nodes in this community*

## Relationships

- [pathlib](pathlib.md) (6 shared connections)
- [json](json.md) (1 shared connections)

## Source Files

- `scripts/test_budgets.py`

## Audit Trail

- EXTRACTED: 92 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the Cairn knowledge wiki. See [index](index.md) to navigate.*