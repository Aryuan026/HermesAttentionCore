# Requirements

- External facts use one sanitized, idempotent Inbox contract with coalescing,
  expiry, and ingest-before-ACK.
- Conversation turns stay in their channel context unless the foreground Agent
  explicitly arranges future state.
- Direct due reminders bypass competition but still wake a live Agent.
- Other owners merge into `attention_opportunity_set.v1`; provider priority is
  a bounded 4% feature with provider and subject diversity.
- The Agent exact-claims at most one source, or atomically closes the exact full
  set as reviewed-quiet. Every terminal path writes canonical receipts.
- Capabilities remain in Hermes native tools/MCP/plugins and are discovered only
  as needed. Attention hints are not permissions.
- Task maintenance stays outside AOS construction.
- The heartbeat is a preflight, not an Agent, sender, or final-content writer.
- One optional adapter failure cannot block another due owner.
- Installation is idempotent, removes retired owned files, and preserves
  independent extensions and private runtime state.
