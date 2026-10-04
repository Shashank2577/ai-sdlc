# TestUnits

> 12 nodes

## Key Concepts

- **TestUnits** (10 connections) — `scripts/test_check_pack_coverage.py`
- **make_pack()** (3 connections) — `scripts/test_check_pack_coverage.py`
- **.setUp()** (2 connections) — `scripts/test_check_pack_coverage.py`
- **.tearDown()** (1 connections) — `scripts/test_check_pack_coverage.py`
- **.test_claimed_directory_reports_its_role()** (1 connections) — `scripts/test_check_pack_coverage.py`
- **.test_main_exits_nonzero_when_a_directory_is_unclaimed()** (1 connections) — `scripts/test_check_pack_coverage.py`
- **.test_main_exits_zero_when_everything_is_claimed()** (1 connections) — `scripts/test_check_pack_coverage.py`
- **.test_report_names_the_unclaimed_directory()** (1 connections) — `scripts/test_check_pack_coverage.py`
- **.test_report_omits_unclaimed_section_when_everything_is_claimed()** (1 connections) — `scripts/test_check_pack_coverage.py`
- **.test_unclaimed_directory_is_reported_with_no_pack()** (1 connections) — `scripts/test_check_pack_coverage.py`
- **Path** (1 connections)
- **A directory with committed code and no owning pack must be reported — the…** (1 connections) — `scripts/test_check_pack_coverage.py`

## Relationships

- [pathlib](pathlib.md) (2 shared connections)

## Source Files

- `scripts/test_check_pack_coverage.py`

## Audit Trail

- EXTRACTED: 13 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the Cairn knowledge wiki. See [index](index.md) to navigate.*