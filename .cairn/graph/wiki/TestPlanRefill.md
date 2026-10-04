# TestPlanRefill

> 10 nodes

## Key Concepts

- **TestPlanRefill** (9 connections) — `scripts/test_refine.py`
- **pm_issue()** (8 connections) — `scripts/test_refine.py`
- **.test_a_ready_item_wins_over_an_earlier_unapproved_one()** (2 connections) — `scripts/test_refine.py`
- **.test_above_the_floor_is_quiet_regardless_of_the_board()** (2 connections) — `scripts/test_refine.py`
- **.test_an_in_progress_pm_item_is_waited_on_not_duplicated()** (2 connections) — `scripts/test_refine.py`
- **.test_at_the_floor_with_a_ready_pm_item_dispatches_it()** (2 connections) — `scripts/test_refine.py`
- **.test_at_the_floor_with_an_unapproved_pm_item_waits()** (2 connections) — `scripts/test_refine.py`
- **.test_the_lowest_ready_pm_item_is_chosen_when_several_exist()** (2 connections) — `scripts/test_refine.py`
- **.test_the_same_board_always_gives_the_same_plan()** (2 connections) — `scripts/test_refine.py`
- **.test_at_the_floor_with_no_pm_work_creates_one()** (1 connections) — `scripts/test_refine.py`

## Relationships

- [pathlib](pathlib.md) (2 shared connections)

## Source Files

- `scripts/test_refine.py`

## Audit Trail

- EXTRACTED: 17 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the Cairn knowledge wiki. See [index](index.md) to navigate.*