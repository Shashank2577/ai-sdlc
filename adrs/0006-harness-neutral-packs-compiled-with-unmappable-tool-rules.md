# ADR-0006: Role packs are harness-neutral; the compiler writes rules it cannot express to `UNMAPPABLE.md` instead of dropping them

**Status:** accepted
**Work item:** Shashank2577/foundry-program#4
**Requirement:** REQ-002

## Context

PRD §3 requires role packs to be harness-neutral — one definition of a
role's charter, skills, budget and tool scope, usable across whichever
harness (claude-code, codex, deepseek, ...) actually runs a session. The
first real pack (`role-packs/developer/`) needed something to turn that
neutral definition into a harness's native config, and needed a stated
answer for the case where a harness's config format cannot express a rule
the neutral pack declares — most concretely, a tool-deny rule with an
interior wildcard, which not every harness's allow/deny syntax supports.

## Options considered

### Option A: Write each role pack directly in every supported harness's native format

- **Cost:** N packs x M harnesses, hand-maintained in parallel. Every
  policy change (a new deny rule, a budget adjustment) is M edits instead
  of one, and nothing catches the day they drift apart.
- **Consequence:** "Harness-neutral" is a claim in the PRD, not a property
  of the repo — two harnesses running the "same" role pack can silently
  enforce different things.

### Option B: One neutral pack per role; a compiler renders it per harness, and a rule the target cannot express is written to `UNMAPPABLE.md`

- **Cost:** Build and maintain `compiler/compile-pack.py` — validation for
  missing files, role/directory mismatches, incomplete budgets and dangling
  escalation templates, all failing loudly with the file named, plus the
  render logic itself per harness target.
- **Consequence:** One source of truth per role. A tool rule the compiler
  cannot map to the target harness's syntax is not silently dropped — it is
  written to `UNMAPPABLE.md` next to the compiled config, so an operator
  can see, per harness, exactly which controls did not make it through.

## Recommendation

Recommend B: a deny rule that silently fails to compile is worse than no
rule at all, because the operator believes a control exists when it does
not. `UNMAPPABLE.md` turns a silent gap into a visible one, at the cost of
building and maintaining the compiler once, centrally, instead of drifting
per-harness packs forever.

## Decision

**Decided:** Option B
**Decided by:** architect/developer session, implemented in PR #12, closing
#4
**Date:** 2026-09-02 (reconstructed from PR #12's merge commit timestamp)

`compiler/compile-pack.py` renders a neutral pack for a target harness,
rejecting a malformed one (missing required file, role/directory mismatch,
unbudgeted role, dangling escalation template) rather than compiling it
partially. A tool rule with, for example, an interior wildcard that the
target harness's allow/deny syntax cannot express is written to
`UNMAPPABLE.md` in the compiled output directory instead of being dropped.

## Consequences

Every future harness target (codex's `compile_codex`, added later, is the
first proof of this) is expected to plug into the same compiler and the
same `UNMAPPABLE.md` convention rather than inventing its own silent-drop
behaviour. Any pack change is validated once, centrally, by
`compiler/test_compile_pack.py`'s `test_every_committed_pack_compiles`, so
a pack that stops compiling for one harness fails CI before it reaches a
dispatched session.
