# Hermes Attention Core rules

Read `skills/attention-steward/references/architecture.md` before architectural
work.

- Conversation channels remain Hermes context. Only explicit future intent may
  create Calendar, Task, or Continuation state.
- External provider facts enter the generic Inbox through narrow adapters. ACK
  only after canonical ingest.
- Actual abilities stay in Hermes native tools, MCP, and plugins. Do not build
  an Attention tool registry or whitelist.
- Attention builds one read-only bounded set. Choice uses exact source claim;
  reviewed-quiet uses exact full-set settlement. No FIFO fallback.
- Cron wakes one normal foreground Agent. Do not launch a nested Agent or turn
  script output into prewritten owner speech.
- Keep secrets, runtime databases, logs, chat text, and receipts out of Git.
- New behavior needs both a legal positive path and a boundary/failure test.
