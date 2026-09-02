<!--
Shape for a release notes entry, per skills/deriving-release-notes-from-trailers.md.
Every bullet must trace back to a commit SHA carrying a Requirement trailer
on the range being released — never to a session's memory of what it did.
-->

## <release name or date range>

<One or two sentences: what this range of commits was about, for a reader
who was not in the room. Not a restatement of the bullets below.>

### REQ-0XX — <requirement text, from requirements/index.md>

- <plain-language change, sourced from the commit subject> (`<sha>`, closes #<issue>)
- <second change under the same requirement, if any> (`<sha>`, closes #<issue>)

### REQ-0XX — <next requirement>

- <change> (`<sha>`, closes #<issue>)

### Untraced

<Commits in this range with no Requirement trailer, or a Work-Item that did
not resolve — named, not silently dropped. "None" if the range is clean.>

- `<sha>` — <subject> — <what's missing, e.g. "no Requirement trailer">
