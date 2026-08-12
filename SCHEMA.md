# Runtime schema

One private SQLite file holds separate owner tables. Sharing a file is a
deployment convenience; Attention is not their writer.

- `agent_events`: generic external Inbox facts, source version, sanitized
  compact payload, refs/hints, coalesce/follow-up, expiry, exact claim.
- `calendar_items`: explicit direct-lane reminders.
- `agent_continuations`: causal goal/stage/due state deliberately resumed later.
- `hermes_tasks`: scheduled, standing, or periodic task definitions.
- `hermes_task_cycles`: separate monthly cycles, forms/results, and history.
- `source_receipts`: terminal source outcomes and compact canonical evidence.
- `runtime_migrations`: idempotent migration receipts.

Source lifecycle is owner-specific. Inbox/Calendar/Continuation normally use
`pending → claimed → settled`; tasks remain `active` across attention looks
unless a one-shot scheduled task reaches its terminal state. Before every AOS
build, heartbeat maintenance returns expired claims to the same owner's
available status. A claimed Inbox predecessor that acquired `superseded_by`
instead becomes `superseded` and cannot settle as a canonical success.

`attention_opportunity_set.v1` is a deterministic read-only candidate view.
Its `eligible_membership` lists every current candidate; `set_id` hashes that
membership after canonical sorting by source kind, ID, and version, never by
dynamic score or display order. `review_membership` contains only the bounded
candidates whose full content is present in `opportunities`, and `review_id`
identifies that exact review scope. Reviewed-quiet settlement may close only
`review_membership`. Candidate capability hints contain broad domains only.
Tool definitions, permissions, MCP configuration, action receipts, and
conversation routing are not part of the AOS schema.

The coordinator owns cross-source transaction orchestration, not source SQL.
Each owner store supplies transaction-aware freeze, freshness validation, and
settlement hooks; `ContinuationStore` supplies transactional creation for a
defer. Sharing one database enables atomic composition without transferring
table ownership to Attention.

Legacy `opportunities` and `receipts` remain audit data. Migration moves only
unambiguous pending continuations, archives pending channel/provider rows
without replay or guessing, and leaves settled history untouched.
