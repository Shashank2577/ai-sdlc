**As the** <persona> **I want** <capability> **so that** <outcome>. → **REQ-0XX[, REQ-0XX]**

<One or two sentences of context: why this now, what bottleneck or request
it traces back to. Not a restatement of the acceptance criteria below.>

Name the exact surface this touches — see
`skills/sizing-and-splitting-a-story.md`: the file(s), function/class, and
test file this extends or creates. An outcome description belongs in the
context above; this line belongs to a developer session with no memory of
this conversation.

Acceptance criteria:
```gherkin
Given <state>
When <action>
Then <observable, checkable result>

Given <state>
When <action>
Then <observable, checkable result>
```

Notes:
- <Anything a developer session needs and would otherwise have to
  rediscover: files already read, dead ends already ruled out, explicit
  non-goals.>

Estimate: <S|M|L> — <one line grounding the size in what the story
actually touches, e.g. "M: one new role-pack directory, mirrors two
existing packs">
