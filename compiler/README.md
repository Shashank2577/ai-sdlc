# Compiler — role pack → harness config

Role packs are harness-neutral (PRD §3). This turns one into config a
specific harness can actually run.

```sh
python3 compiler/compile-pack.py --check                       # validate every pack
python3 compiler/compile-pack.py --role developer --out build/ # render one
python3 compiler/test_compile_pack.py                          # 13 tests
```

`--check` runs in CI on every PR touching `role-packs/` or `compiler/`
(`.github/workflows/packs.yml`), so a pack cannot be edited into a state
where the role stops being dispatchable.

## What it produces

For `claude-code`, into `<out>/<role>/claude-code/`:

| File | Contents |
|---|---|
| `system-prompt.md` | charter, budget, forbidden actions, HITL triggers, then every skill in `skills/` |
| `settings.json` | `permissions.allow` / `permissions.deny` derived from `tools.yaml` |
| `UNMAPPABLE.md` | written only when some tool rule has no equivalent in this harness |

## What it validates

A pack fails to compile — loudly, with the offending file named — when it
is missing one of `pack.yaml` / `charter.md` / `tools.yaml` / `policy.yaml`,
when `pack.yaml:role` disagrees with the directory name, when any of
`budgets.{turns,tokens,wall_clock_minutes,max_retries}` is absent, when
`escalation.template` points at a file that does not exist, or when any
YAML is malformed.

The budget rule is the strict one on purpose: an unbudgeted role cannot be
dispatched, so a pack without a complete budget is not a pack.

## UNMAPPABLE.md, and why it exists

`tools.yaml` uses shell globs. Claude Code matches Bash permissions on a
*prefix*, so `git push*--force*` — wildcard in the middle — has no
equivalent rule.

The compiler could drop it. It doesn't, because a deny rule that silently
failed to compile is worse than no deny rule at all: you would believe you
had a control you did not have. Unmappable rules are written to
`UNMAPPABLE.md` and reported by `--check`, and each one needs a structural
control instead. Force-push, for instance, is genuinely prevented by
`allow_force_pushes: false` on the protected branch — not by a prompt.

## Adding a harness

Write `compile_<harness>(pack) -> dict[filename, content]` and register it
in `HARNESSES`. `read_pack()` and its validation are shared, so a new
harness inherits every check above. Codex would render `AGENTS.md` plus a
sandbox policy; DeepSeek, its own config surface.

Packs declare what they support in `pack.yaml:harness_compat`; compiling a
pack for a harness it does not claim to support is an error, not a warning.
