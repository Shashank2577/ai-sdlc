# Architecture decision records

PRD §14. One file per structural decision, numbered sequentially:
`adrs/NNNN-title-in-kebab-case.md`.

Written by the architect role pack (`role-packs/architect/`) from
`role-packs/architect/templates/adr.md`. CODEOWNERS routes this directory
to a human architect — an ADR merged by the agent that proposed it is not a
decision anyone made.

Not every change gets one; see
`role-packs/architect/skills/when-not-to-write-an-adr.md` for the boundary.

## The citation rule

Every ADR names the work item(s) — issue or pull request — where the
decision was actually taken, in its `Work item:` field and again in
Context. An ADR is a record of a decision that was made, not a design
proposal dressed as one; if the reasoning behind an older decision has to
be reconstructed from the artefacts rather than quoted from them, the ADR
says so plainly (in the `Decision` section's date or provenance line)
instead of presenting a reconstruction as if it were contemporaneous.
Backfilled ADRs — recording a decision already taken before this format
existed — are marked `Status: accepted` with a reconstruction note, not
`proposed`.
