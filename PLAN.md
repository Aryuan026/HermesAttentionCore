# Plan

## Stable core

- Generic external Inbox adapters with ingest-before-ACK.
- Direct Calendar lane plus unified Continuation/Task/Inbox attention set.
- Bounded 4% provider priority, diversity, exact claim, canonical queue
  identity, discrete review semantics, and exact bounded-review quiet CAS.
- Pre-build expired-lease recovery and claimed-source freshness validation.
- Live native Cron Agent with progressive Hermes tool/MCP discovery.
- Portable installer, migration, Skills, and public adapter documentation.

## Extension rule

New external facts use Inbox adapters. New abilities use Hermes native
tools/MCP/plugins. New conversation channels connect to Hermes normally. A new
internal source owner requires an explicit product and schema change.

## Non-blocking portability hardening

- Attach-mode installation already rejects an incompatible native Cron API
  before job mutation. A later bind/update/persistence-verification failure can
  still leave a newly created or edited heartbeat job behind; a future
  installer pass should snapshot the old job and roll back that mutation.
