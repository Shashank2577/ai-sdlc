# adr_text

> 31 nodes

## Key Concepts

- **adr_text()** (14 connections) — `dashboards/test_adr.py`
- **test_adr.py** (11 connections) — `dashboards/test_adr.py`
- **TestParseAdr** (7 connections) — `dashboards/test_adr.py`
- **TestRenderHtml** (7 connections) — `dashboards/test_adr.py`
- **TestRenderBody** (5 connections) — `dashboards/test_adr.py`
- **TestScanAdrs** (5 connections) — `dashboards/test_adr.py`
- **TestLinkSupersession** (4 connections) — `dashboards/test_adr.py`
- **.test_chain_of_three_links_each_hop()** (2 connections) — `dashboards/test_adr.py`
- **.test_dangling_superseded_by_does_not_crash()** (2 connections) — `dashboards/test_adr.py`
- **.test_superseding_record_gets_backlink()** (2 connections) — `dashboards/test_adr.py`
- **.test_multiple_requirements_split_and_sorted()** (2 connections) — `dashboards/test_adr.py`
- **.test_req_not_in_index_is_flagged_unknown()** (2 connections) — `dashboards/test_adr.py`
- **.test_superseded_status_is_parsed_with_target_id()** (2 connections) — `dashboards/test_adr.py`
- **.test_well_formed_record_parses_every_field()** (2 connections) — `dashboards/test_adr.py`
- **.test_renders_self_contained_html_and_escapes_titles()** (2 connections) — `dashboards/test_adr.py`
- **.test_req_link_points_at_traceability_anchor()** (2 connections) — `dashboards/test_adr.py`
- **.test_superseded_chain_renders_both_directions()** (2 connections) — `dashboards/test_adr.py`
- **.test_unknown_req_is_marked_not_linked()** (2 connections) — `dashboards/test_adr.py`
- **.test_malformed_file_is_listed_not_dropped()** (2 connections) — `dashboards/test_adr.py`
- **.test_readme_is_excluded_but_records_are_included()** (2 connections) — `dashboards/test_adr.py`
- **.test_missing_heading_is_a_parse_error_not_a_crash()** (1 connections) — `dashboards/test_adr.py`
- **.test_missing_status_is_a_parse_error()** (1 connections) — `dashboards/test_adr.py`
- **.test_h3_subheading_becomes_h5()** (1 connections) — `dashboards/test_adr.py`
- **.test_leading_bold_label_is_converted()** (1 connections) — `dashboards/test_adr.py`
- **.test_literal_double_asterisk_glob_is_not_treated_as_bold()** (1 connections) — `dashboards/test_adr.py`
- *... and 6 more nodes in this community*

## Relationships

- [pathlib](pathlib.md) (4 shared connections)

## Source Files

- `dashboards/test_adr.py`

## Audit Trail

- EXTRACTED: 47 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the Cairn knowledge wiki. See [index](index.md) to navigate.*