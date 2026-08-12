# Hermes Attention Core rules

Read `skills/attention-steward/references/architecture.md` before architectural
work.

- Conversation channels remain Hermes context. Only explicit future intent may
  create Calendar, Task, or Continuation state.
- External provider facts enter the generic Inbox through narrow adapters. ACK
  only after canonical ingest.
- Actual abilities stay in Hermes native tools, MCP, and plugins. Do not build
  an Attention tool registry or whitelist.
- Attention builds one read-only candidate view. Choice uses an exact source
  claim; reviewed-quiet settles only the exact bounded `review_membership`
  whose full content was shown. `set_id` must never depend on score order. No
  FIFO fallback.
- Review identity includes discrete presented semantics such as a task's
  `attention_reason`, never continuously changing scores or freshness.
- A selected focus must exact-claim both `source_version` and `review_version`.
  Persist the latter through validate/settle/defer; never let an older task
  phase authorize a side effect, and never fold it into source identity.
- Recover expired claims before build. A claimed Inbox predecessor superseded
  by newer coalesced state must fail freshness validation before side effects.
- Cron wakes one normal foreground Agent. Do not launch a nested Agent or turn
  script output into prewritten owner speech.
- Keep secrets, runtime databases, logs, chat text, and receipts out of Git.
- Inbox identity/routing fields are validated, never silently truncated.
- New behavior needs both a legal positive path and a boundary/failure test.
