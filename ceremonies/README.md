# Ceremony declarations

One file per ceremony named in PRD §5 / REQ-006: `standup.yaml`,
`refinement.yaml`, `planning.yaml`, `review.yaml`, `retro.yaml`. Each
declares what it consumes, produces, and escalates — reviewable here
instead of buried in workflow YAML.

## Schema

Every file carries exactly these eight keys. No others — a ceremony that
needs a ninth key is a sign the schema is wrong, not a reason to add one
quietly.

```yaml
ceremony: <name>
cadence: <cron string, or the event that triggers it>
role: <one of the eight role-packs/* names — the pack dispatched to run
       it, or, for a ceremony that is pure scripted automation with no
       agent session, the pack that owns and maintains the
       implementation (say which, in a comment)>
consumes: [<what it reads>]
produces: [<the artifact(s) it must leave behind>]
artifact_is: issue comment | dashboard page | new issues | label change
escalates_when: [<conditions that end it in needs-human — or, honestly,
                  "nothing today" if no such path exists yet>]
owner: <a role-pack name, or `human`>
```

`standup.yaml`, `refinement.yaml` and `retro.yaml` describe ceremonies that
already run; they were checked against the workflow and script source, not
guessed (see #114's PR body for exactly how). `planning.yaml` and
`review.yaml` declare an intended contract for ceremonies that do not run
yet — a devops story implements against them.

## What still needs to exist: `scripts/check-ceremonies.py`

This directory does not include that script or its tests. `delivery-lead`'s
write scope is `policies/**`, `ceremonies/**` and its own pack directory
(`role-packs/delivery-lead/policy.yaml:write_scope`); `scripts/**` is not in
it, and the same policy's `forbidden` list names
`writing_application_code` and `writing_tests` explicitly. Writing that
script from this role would be exactly the boundary the charter says to
stop at and say so, not quietly cross.

The spec, so whichever role picks it up (`developer` — `scripts/**` and
`tests/**` are both in its write scope) does not have to re-derive it from
this README:

- **Load** every `ceremonies/*.yaml`. Fail loudly on a YAML parse error —
  cite the file.
- **Required keys**: exactly the eight above are present. Missing any ⇒
  fail, citing the file and the missing key(s).
- **Unknown keys are rejected, not ignored**: any key outside the eight ⇒
  fail, citing the file and the unexpected key(s). (`yaml.safe_load` gives
  you a dict; diff its keys against the known set — do not `.get()` past
  the extras.)
- **`role` names a real pack**: one of the eight `role-packs/*/` directory
  names (read them from the filesystem, don't hardcode the list — a ninth
  pack should not require editing this checker).
- **`artifact_is` is one of the known kinds**: `issue comment`,
  `dashboard page`, `new issues`, `label change`. Anything else ⇒ fail,
  citing the file and the value.
- **No two ceremonies claim the same cadence slot**: collect every file's
  `cadence` value verbatim and fail on an exact duplicate, citing both
  files. (This is a string-equality check, not a cron-schedule-overlap
  solver — two different cron expressions that happen to fire at the same
  minute on some calendar are out of scope; the ACs ask for "no two
  ceremonies claim the same... slot", i.e. the same declared string.)
- **`consumes`, `produces`, `escalates_when` are non-empty lists**: each
  must have at least one entry — an empty list is indistinguishable from
  the field being forgotten.
- Exit non-zero with all failures collected and printed together (not
  fail-fast on the first file), so a PR fixing one ceremony sees every
  other problem in the same run rather than discovering them one push at a
  time. Wire it into CI the same way `scripts/dod-check.sh` and
  `scripts/check-test-wiring.sh` are wired: a required check, plus a test
  file (`scripts/test_check_ceremonies.py`, matching this repo's existing
  `test_*.py` naming for Python checkers) covering at least: a valid set of
  five passes; a missing key fails; an unknown key fails; an unknown
  `role` fails; an unknown `artifact_is` fails; two files sharing a
  `cadence` fails.
