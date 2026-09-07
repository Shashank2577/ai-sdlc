# Skill — judging deploy readiness

## Start from the ladder, not the diff

Read `policies/environments.yaml` before the PR. It already states, per
environment: promotion order, who owns rollback, what "unsupervised" means,
and whether a human reviewer is required. Your job is to check the change
in front of you against those stated facts, not to re-derive them.

## The rollback question is always "for this change specifically"

`policies/environments.yaml`'s `prod` entry says rollback is "redeploy the
previous release tag through the same gated workflow". That is a real plan
for a change that is pure code with no persistent side effect. It is not a
real plan, unmodified, for a change that:

- Adds or alters a database migration — redeploying the old tag does not
  undo a migration that already ran.
- Changes a message format, API contract, or file layout another running
  component depends on — the old tag may not be able to read what the new
  one wrote.
- Introduces a one-way action (sending an email, charging a payment,
  deleting data) — nothing about redeploying an old binary un-sends it.

If any of these apply, say so by name and ask for the specific mitigation
(a reversible migration, a compatibility window, a dry-run flag) rather
than accepting the generic plan as sufficient.

## The blast-radius question

For each environment the change could reach: if this fails after
promotion, what actually breaks? Just this service, or does something
downstream depend on the new behavior already? Who is paged, and does
`policies/environments.yaml`'s named `rollback.owner` match who would
actually be reachable.

## Checking the human gate is still real

`prod`'s entry declares `human_reviewer_required: true` and names
`required_reviewers`. This is enforced by the GitHub Environment's
protection rule, not by anything in this repository's files — so the
question worth asking on a diff that touches `.github/workflows/deploy*.yml`
or `infra/**` is whether it could route a promotion around that
`environment:` key entirely, not whether the YAML in this repo looks safe
in isolation.

## Writing the report

State plainly: ready, not-ready-because-<specific gap>, or a named gap that
does not block this story but should be tracked (file it as a bug issue).
Never "looks risky" with no cited gap — that is not actionable by whoever
reads it next, agent or human.
