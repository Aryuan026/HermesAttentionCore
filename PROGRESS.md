# Progress

## 0.1.0

- Published the generic owner-store runtime with Calendar, Continuation, Task,
  Inbox, receipts, migration, and deterministic attention scoring.
- Added exact source claims and the first atomic reviewed-quiet settlement
  path; the lifecycle hardening below narrows its scope to fully shown members.
- Added a trusted external adapter registry and an AI-forum integration guide.
- Added clean install/upgrade behavior and normal Hermes Cron Agent mode.
- Added positive and negative tests for channel, capability, adapter, migration,
  lifecycle, privacy, and installer boundaries.
- Added opt-in native Cron session binding so a heartbeat delivery can remain
  causally available to replies without coupling Attention to any channel.

## Unreleased — lifecycle hardening

- Added heartbeat-level expired-claim recovery before AOS build, so an Agent
  crash cannot leave the only candidate for one owner permanently invisible.
- Split canonical full eligible `set_id` from bounded displayed `review_id`;
  reviewed-quiet now settles only candidates whose full content was shown.
- Made set identity independent of dynamic score and display order.
- Added freshness validation for claimed Inbox rows superseded by newer
  coalesced facts, with canonical-success settlement rejection for stale work.
- Enforced Inbox depth/node/container/byte/reference bounds and secret
  sanitization inside the Store rather than only in adapter guidance.
- Moved cross-owner quiet/defer composition onto transaction-aware Store APIs
  and added a real Hermes Cron API probe for native session binding.
- The previous portable checkpoint passed 41 tests. The current local suite
  passes 52 and all three public Skills validate.
- Added discrete `review_version` semantics, so a warning review cannot quiet
  an overdue presentation of the same task while score-only movement remains
  identity-neutral. Inbox identity/routing fields now reject overlength values,
  and attach mode probes native Cron compatibility before any job mutation.
- Extended `review_version` across selected focus open, persisted claim state,
  pre-action validation, settle, and defer. A warning presentation is rejected
  both when it changes before claim and when it becomes overdue after claim;
  neither path can write an acted receipt. Existing databases upgrade the new
  claim field idempotently without changing stable source/set identity.
- Generic upgrades now tighten the installer-owned
  `~/.hermes/attention` directory to 0700, including homes created by an older
  release with a more permissive mode.
- A production canary exposed database-path drift between a regenerated
  heartbeat wrapper and a foreground gateway. The installer now accepts one
  explicit canonical database, pins it into both installed entrypoints, and
  makes an unbound heartbeat fail visibly instead of creating another store.
