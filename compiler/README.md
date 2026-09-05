# Compiler — role pack → harness config

Role packs are harness-neutral (PRD §3). This turns one into config a
specific harness can actually run.

Prior art: [awslabs/aidlc-workflows](https://github.com/awslabs/aidlc-workflows)
(MIT-0) ships thin per-harness surfaces over one harness-neutral `core/` for
seven targets (claude, codex, copilot, cursor, kiro, kiro-ide, opencode).
This file follows the same architecture at v0 scale — one `render_role_doc`
shared across targets, one `compile_<harness>` per surface. `compile_opencode`
also borrows a specific fact from their `harness/opencode/opencode.json`: an
opencode `permission.bash` rule is a real glob (last match wins), not a
prefix rule — see that function's docstring.

```sh
python3 compiler/compile-pack.py --check                                     # validate every pack, claude-code
python3 compiler/compile-pack.py --check --harness codex                     # same, codex
python3 compiler/compile-pack.py --check --harness opencode                  # same, opencode
python3 compiler/compile-pack.py --role developer --out build/               # render one, claude-code
python3 compiler/compile-pack.py --role developer --harness codex --out build/  # render one, codex
python3 compiler/compile-pack.py --role developer --harness opencode --out build/  # render one, opencode
python3 compiler/test_compile_pack.py                                        # tests
```

**Compiles vs. has run a session.** `--check` only proves a pack renders
into valid-looking config for a harness — it never runs one. As of this
writing, `claude-code` is the only target that has run a live dispatched
session and produced a merged pull request (`.github/workflows/dispatch.yml`
hard-codes `--harness claude-code` and the `claude-code-action` step; no
role pack declares `codex` or `opencode` in `harness_compat` yet). Treat
`codex` and `opencode` as compiler-verified, not dispatcher-proven, until
that changes.

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

For `codex`, into `<out>/<role>/codex/`:

| File | Contents |
|---|---|
| `AGENTS.md` | same content as `system-prompt.md` above — charter, budget, forbidden actions, HITL triggers, skills |
| `sandbox-policy.toml` | a `[profiles.<role>]` fragment setting `sandbox_mode` / `approval_policy` |
| `UNMAPPABLE.md` | every `tools.yaml` shell rule, always — see below |

For `opencode`, into `<out>/<role>/opencode/`:

| File | Contents |
|---|---|
| `AGENTS.md` | same content as `system-prompt.md` above — opencode auto-reads a project-root `AGENTS.md`, same convention as Codex |
| `opencode.json` | a `permission.bash` glob map (`allow`/`ask`/`deny`) derived from `tools.yaml`, `"*": "ask"` catch-all first |

All three targets also emit `token-secret` and `dispatchable-from`, unchanged —
none is harness-specific.

Codex's sandbox is a coarse filesystem-access mode (`read-only` /
`workspace-write` / `danger-full-access`) plus an `approval_policy`
(`untrusted` / `on-failure` / `on-request` / `never`) — config.toml keys,
not a per-command rule list. It has no equivalent of Claude Code's
`Bash(cmd:*)` prefix match, so `to_bash_rule`'s allow/deny shape cannot be
forced onto it: unlike the claude-code target, *every* `tools.yaml` shell
rule ends up in `UNMAPPABLE.md`, not only the ones with an interior
wildcard. `sandbox-policy.toml` sets `approval_policy = "never"` — the
same reasoning `compile_claude_code` gives for `bypassPermissions`, a
headless session cannot answer a prompt — scoped to `workspace-write`
rather than full access.

opencode's `permission.bash` is different again: it is a genuine glob
(`*` matches anywhere, and the *last* matching rule wins), not a prefix
match, confirmed by reading `harness/opencode/opencode.json` in
awslabs/aidlc-workflows. `tools.yaml`'s shell rules are already shell
globs, so every allow/deny entry — including the interior-wildcard one
that defeats both other targets — maps across unchanged, allow written
before deny so a specific deny outranks a broader allow. `compile_opencode`
never writes `UNMAPPABLE.md`.

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
harness inherits every check above. `codex` (`AGENTS.md` + a sandbox
policy) and `opencode` (`AGENTS.md` + a permission glob map) are
implemented this way; Kiro, Cursor, Copilot, and DeepSeek are not —
`awslabs/aidlc-workflows`'s `harness/` tree is the reference for what each
of those would need to differ on (permission model, tool naming, settings
format, prompt assembly are all visible there).

Compiling for a harness is not the same claim as a role having run a
session under it — see "Compiles vs. has run a session" above. Packs
declare what they support in `pack.yaml:harness_compat`; compiling a pack
for a harness it does not claim to support is an error, not a warning, and
today no pack claims `opencode` there — adding a `compile_*` function does
not, by itself, make any role dispatchable under it.

## Adding a harness the dispatcher can actually run

The five files above are necessary but not sufficient. `.github/workflows/dispatch.yml`
still hard-codes `--harness claude-code` and a `claude-code-action` step;
making a second target dispatchable means adding a harness-selection branch
there (or an equivalent CI action) — outside `compiler/`'s scope, and
outside what a compiler change alone can prove. Until a role pack opts in
via `harness_compat` *and* the dispatcher can invoke that harness's CLI
headlessly, a `compile_*` function is verified by `test_compile_pack.py`
only, not by a live run.
