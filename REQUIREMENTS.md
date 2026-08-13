# Requirements

## Product

- External provider facts use one sanitized, idempotent Inbox contract with
  coalesce/supersede, expiry, and ingest-before-ACK ordering.
- One optional adapter failure is visible in operator logs but cannot block a
  due item already owned by Calendar, Continuation, Task, or another Inbox row.
- QQ/mobile/Feishu/CLI chat remains normal foreground context. Only explicit
  future intent writes Calendar, Continuation, or Task state.
- Direct due reminders bypass AOS competition but wake a live Agent.
- Other due owners merge into `attention_opportunity_set.v1`; provider priority
  is exactly a bounded 4% feature, with provider/subject diversity.
- The model exact-claims at most one chosen source plus the discrete review
  meaning it actually saw, or atomically closes only the exact bounded review
  membership whose complete content it received; hidden eligible candidates
  remain available for later review.
- Full eligible membership has a canonical score-independent `set_id` for
  queue/CAS diagnostics. The bounded displayed membership has a separate
  `review_id`; ranking changes cannot rewrite set identity. Each review member
  also binds discrete presented semantics such as `attention_reason`, while
  continuous freshness, aging, due proximity, and score remain outside IDs.
- Heartbeat maintenance recovers every expired source claim before AOS build.
  A claimed Inbox row superseded by a newer coalesced fact fails freshness
  validation and cannot receive a canonical success receipt.
- Focus open rejects an old review meaning before claim. The claimed
  `review_version` remains durable through validate, settle, and defer, so a
  warning that becomes overdue cannot authorize a later side effect or acted
  receipt.
- The live foreground Agent discovers the minimum necessary capability through
  Hermes native tool/MCP paths, observes authoritative results, and decides
  fresh speech or silence.
- Starting Attention must not remove, duplicate, enumerate, or whitelist all
  Hermes tools.
- Task maintenance stays outside AOS. Scheduled warning/grace/expiry, standing
  meaningful-state surfacing, monthly cycles, completion forms/history,
  `Asia/Shanghai`, and local due proximity remain Hermes-specific semantics.
- The heartbeat script cannot be an Agent, sender, or final content generator.
- External Inbox bounds and secret redaction are enforced by `InboxStore`, not
  merely promised by adapter documentation.
- Stable Inbox identity and routing fields reject overlength input rather than
  truncating distinct values into aliases. Display-only fields may be bounded.
- An attach-to-session install probes the installed native Cron API before any
  real heartbeat job is created or edited.
- Installation binds the CLI and heartbeat to one canonical database path.
  An entrypoint without that binding fails visibly instead of creating a
  second default store.

## Acceptance

Code Green requires positive and negative tests for every boundary above,
validated Skills, clean migration, and no legacy transcript/no-agent path.

Runtime Green requires separate evidence stages:

```text
available → delivered → selected → requested → executor_started
→ canonical_receipt → visible_projection_or_deliberate_silence
```
