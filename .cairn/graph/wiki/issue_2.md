# issue

> 24 nodes

## Key Concepts

- **issue()** (20 connections) — `scripts/test_sync_project.py`
- **TestPlanAdditions** (6 connections) — `scripts/test_sync_project.py`
- **TestRequirementExtraction** (6 connections) — `scripts/test_sync_project.py`
- **TestRoleAndVerdict** (6 connections) — `scripts/test_sync_project.py`
- **TestStatusMapping** (5 connections) — `scripts/test_sync_project.py`
- **.test_a_closed_issue_missing_from_the_board_is_not_planned()** (2 connections) — `scripts/test_sync_project.py`
- **.test_additions_are_ordered_by_issue_number()** (2 connections) — `scripts/test_sync_project.py`
- **.test_an_issue_already_on_the_board_is_not_replanned()** (2 connections) — `scripts/test_sync_project.py`
- **.test_an_open_issue_missing_from_the_board_is_planned()** (2 connections) — `scripts/test_sync_project.py`
- **.test_every_open_issue_already_on_the_board_plans_nothing()** (2 connections) — `scripts/test_sync_project.py`
- **.test_falls_back_to_the_whole_body_without_a_marker()** (2 connections) — `scripts/test_sync_project.py`
- **.test_ids_are_sorted_and_deduplicated()** (2 connections) — `scripts/test_sync_project.py`
- **.test_no_requirements_leaves_the_field_alone()** (2 connections) — `scripts/test_sync_project.py`
- **.test_reads_the_convention_marker()** (2 connections) — `scripts/test_sync_project.py`
- **.test_the_marker_is_authoritative_over_incidental_mentions()** (2 connections) — `scripts/test_sync_project.py`
- **.test_no_role_label_leaves_the_field_alone()** (2 connections) — `scripts/test_sync_project.py`
- **.test_qa_defaults_to_pending()** (2 connections) — `scripts/test_sync_project.py`
- **.test_qa_labels_map_to_verdicts()** (2 connections) — `scripts/test_sync_project.py`
- **.test_rejected_wins_when_both_verdicts_are_present()** (2 connections) — `scripts/test_sync_project.py`
- **.test_role_label_maps_to_the_role_field()** (2 connections) — `scripts/test_sync_project.py`
- **.test_blocked_wins_over_other_status_labels()** (2 connections) — `scripts/test_sync_project.py`
- **.test_closed_outranks_any_label()** (2 connections) — `scripts/test_sync_project.py`
- **.test_each_status_label_maps_to_its_column()** (2 connections) — `scripts/test_sync_project.py`
- **.test_no_status_label_is_todo()** (2 connections) — `scripts/test_sync_project.py`

## Relationships

- [BoardRef](BoardRef.md) (5 shared connections)

## Source Files

- `scripts/test_sync_project.py`

## Audit Trail

- EXTRACTED: 43 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the Cairn knowledge wiki. See [index](index.md) to navigate.*