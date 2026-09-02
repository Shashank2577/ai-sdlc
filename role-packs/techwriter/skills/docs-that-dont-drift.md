# Skill — docs that don't drift

## The failure mode this prevents

A doc that restates the code — "this function takes a role name and returns
its budget" right above a function that visibly does exactly that — looks
helpful the day it is written. It is dead weight the day someone changes
the function's signature and does not update the paragraph, because nothing
forces them to. Six months on, it is not neutral; it is actively lying to
the next reader, who trusts the doc over the code because that is what docs
are for.

The fix is not "remember to update it." The fix is to not write the kind of
sentence that can go stale in the first place.

## The standard: why, not what

`dashboards/README.md` and `compiler/README.md` are the reference. Read
either one before writing a docs PR. Both follow the same shape:

- A sentence or two on why the thing exists, or why it works the way it
  does — the constraint, the incident, the tradeoff it resolved.
- A pointer at the code, or a `--check`-style command, for what it actually
  does right now.
- Worked examples of the command line, not a description of what the flags
  mean in prose the flags already say.

Compare `compiler/README.md`'s "UNMAPPABLE.md, and why it exists" section:
it does not enumerate what fields the file contains — it explains why the
compiler refuses to silently drop an unmappable rule. That paragraph cannot
go stale the way "the file contains a list of unmapped rules" would,
because the reasoning behind a design decision does not change even when
the code around it does.

## A test you can apply to a draft paragraph

Ask: if the implementation changed tomorrow in a reasonable way, would this
paragraph become wrong? If yes, it is restating the code, not explaining
it, and it belongs as a link to the source instead.

## What this means in practice

- Prefer "see `role-packs/README.md` for the pack shape" over retyping the
  directory tree a second time.
- When you must show a command or a config shape, copy it from the actual
  file (or run it) rather than typing it from memory — the same discipline
  as `skills/deriving-release-notes-from-trailers.md`, applied to code
  instead of commits.
- Write down the *why* even when it feels obvious to you right now. It will
  not be obvious to the next reader, and it is the one part of the doc that
  the code itself cannot say for you.
