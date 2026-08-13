# AI start here

Hermes Attention Core is a channel-neutral attention layer: it decides what
deserves one live look, while Hermes keeps authority over tools, context, and
speech.

Read in this order:

1. [`skills/attention-steward/references/architecture.md`](skills/attention-steward/references/architecture.md) — product contract.
2. [`REQUIREMENTS.md`](REQUIREMENTS.md) and [`SCHEMA.md`](SCHEMA.md) — invariants and data model.
3. [`docs/zh-architecture-guide.md`](docs/zh-architecture-guide.md) — bilingual-friendly implementation map.
4. `src/hermes_attention/{attention,inbox,calendar,continuations,tasks,claims,presence,runtime}.py` — production path.

Keep these boundaries: external facts → Inbox; explicit future intent →
Calendar/Task/Continuation; abilities → Hermes native MCP/tools; channels →
ordinary Hermes context. Never add transcript ingestion, an Attention-owned
tool registry, prewritten delivery, FIFO fallback, a second database path, or
an empty-wake action menu. `routine_presence` is a cadence gate, not an AOS
owner or a repeating leisure task.

Verify with `PYTHONPATH=src python3 -m unittest discover -s tests -v`.
