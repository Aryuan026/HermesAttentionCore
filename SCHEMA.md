# Runtime schema

One private SQLite file contains separate owner tables:

- `agent_events`: generic external Inbox facts and exact claim state.
- `calendar_items`: explicit direct-lane reminders.
- `agent_continuations`: causal goal/stage/due state.
- `hermes_tasks`: scheduled, standing, and periodic definitions.
- `hermes_task_cycles`: separate monthly cycle results and history.
- `source_receipts`: canonical source settlements.
- `runtime_migrations`: idempotent migration receipts.

`attention_opportunity_set.v1` is a deterministic read-only view. Its `set_id`
includes exact full eligible membership even when the model packet is bounded
by diversity. Capability hints are broad domains; tool definitions, permissions,
MCP configuration, delivery routing, and conversation text are not AOS fields.
