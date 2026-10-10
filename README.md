# Hermes Attention Core

**Give Hermes a sense of what matters next.**

A portable, channel-neutral attention layer for one owner-operated Hermes Agent.
External facts, deliberate reminders, continuations and meaningful task changes
become a small field of possibilities. The live Agent decides whether to act,
speak freshly or stay quiet using the abilities it already has.

## Compatibility

Last reviewed: **2026-10-10**. Core version: **0.1.0**; Python: **3.9+**.
This is a runtime plus Skills/native Cron integration, **not** a manifest-v2
request plugin and not a replacement Hermes memory backend.

- **Hermes 0.21.5 — current verified installation seam.** Public Core
  `39112759f2d43a6c228e6a0c089f2e8dda33387b` passed the real CLI create/edit
  and native session-binding regression against the fixed owner-maintained
  0.21.5 host. Python 3.11 ran 60/60; Python 3.12 ran 59 with one real-host
  skip. This qualifies that seam, not every provider or plain upstream build.
- **Hermes 0.20.5 — historical runtime lineage.** The matching private Runtime
  has recorded live wake, quiet and source/action canaries. Those results are
  not a fresh deployment or full-host qualification of current public Core.
- **Hermes 0.21.3 and other versions — no separate current-Core
  qualification recorded here.** Do not infer support from a version range
  or from another component's migration tests.

Core itself needs no Continuity/Global Hot host patch set. It does require a
working `hermes cron` command, native Cron preflight/Agent execution and the
`cron.jobs` read/update APIs for session attachment. The installer probes
attach compatibility before job mutation. Create uses a **positional schedule**
and native default Agent mode; only edit uses `--schedule` and `--agent`.
A public Core test pass is not evidence that Core replaced a private deployment.

## Highlights

- **Stimulus, ability and mouth are separate.** Inbox adapters supply compact
  facts; Hermes tools/MCP/plugins supply abilities; channels supply delivery.
  A new integration does not require changing the Attention core.
- **Attention is not FIFO.** Calendar reminders have a direct lane; other
  sources use bounded salience, aging and provider/subject diversity. Provider
  priority is only a bounded 4% hint.
- **Quiet is an exact decision.** `reviewed-quiet` closes only the fully shown,
  bounded review—not hidden candidates the Agent never considered.
- **A selected focus stays tied to its meaning.** Exact source/review versions
  survive claim, pre-action validation, settle and defer. A warning that turns
  overdue cannot silently authorize an old claim.
- **An empty pool does not switch agency off.** A throttled presence opportunity
  can wake the same Agent with `pool_state: empty`, without a fake task,
  prescribed action menu or prewritten speech.
- **No second tool universe.** Native tools, MCP permissions, personality,
  conversation history and long-term memory remain Hermes's responsibility.

中文速览：它只帮 Hermes 判断“此刻什么值得看一眼”。真正醒来的仍是活的 Agent；
消息、工具和记忆各归其位，行动与安静都可以成为诚实的结果。

## How it works

```text
external facts → Inbox adapters ┐
explicit future intent → stores ├→ bounded attention → native Cron Agent
empty pool → presence cadence ──┘                         │
native Hermes tools / MCP ────────────────────────────────┘
                                    action + fresh speech / silence
```

Calendar, Continuation, Task and Inbox retain their own state. The coordinator
builds one read-only Attention Opportunity Set. Its eligible `set_id` is
score-independent; the smaller, fully presented `review_id` has exact
membership. Expired claims are recovered before build, and superseded facts
fail freshness validation before side effects.

Heartbeat performs preflight only: it does not launch a nested Agent, execute
an action menu or deliver script output as owner speech. Ordinary QQ/mobile/
Feishu/CLI turns are not automatically converted to events or tasks.
Only explicit future intent creates a reminder, task or continuation.

## Installation

Use an isolated Python environment and a compatible Hermes already on PATH.
To reproduce the reviewed Core installation seam, pin its full source ref:

```bash
git clone https://github.com/Aryuan026/HermesAttentionCore.git
cd HermesAttentionCore
git checkout 39112759f2d43a6c228e6a0c089f2e8dda33387b
python3 scripts/install_hermes.py --install-cron --deliver <platform>
```

Replace angle-bracket placeholders with your platform/native values. The
installer writes the generic runtime, three Skills and one canonical heartbeat.
It does not enumerate, enable or disable Hermes capabilities.

For replies to retain the heartbeat's causal context in the native session:

```bash
python3 scripts/install_hermes.py \
  --install-cron --deliver <platform> \
  --attach-to-session --origin-platform <platform> \
  --origin-chat-id <native-chat-id>
```

Add `--origin-user-id` for a per-user-isolated group and
`--origin-thread-id` for a topic. Rebind the origin when changing mouth;
successful delivery is mirrored into that session without importing its raw
transcript into Attention.

## Configuration and limits

- Default Cron poll: **every 15 minutes**; a poll is not an Agent wake.
- Empty-pool cadence: **120-minute minimum gap**, up to **3,600 seconds** of
  stable jitter, timezone **Asia/Shanghai**, sleep-window coalescing
  **01:00–08:00**. Populated attention bypasses that empty-pool throttle.
- Set cadence and schedule with the installer flags shown by
  `python3 scripts/install_hermes.py --help`; keep all values explicit on
  upgrades if you changed the defaults.
- If the canonical DB is outside the default Hermes home, pass
  `--attention-db /absolute/private/attention.sqlite3` on every install/upgrade.
  Both installed entrypoints pin the same DB; an unbound entrypoint fails
  instead of inventing another store.
- Inbox enforces payload/reference bounds, identity validation, sanitization,
  idempotency, coalescing and expiry. Runtime databases, credentials, chat text,
  logs and generated receipts stay out of Git.

To add a forum, mailbox or other event source, implement the
[Inbox adapter contract](skills/attention-runtime-setup/references/external-inbox-adapters.md):
`build_poll(stores)` maps bounded facts to `AgentEvent`, commits through
`stores.inbox.ingest()`, then ACKs upstream.

```bash
hermes-attention adapters register --name ai-forum --module my_forum_attention
```

Reply/action abilities must be registered separately through native Hermes
tools or MCP. Receiving an event grants no action permission.

## Verification

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -B -m unittest discover -s tests -v
```

For real Cron create/edit/session-binding tests, use an environment containing
the exact Hermes host's dependencies and set
`HERMES_ATTENTION_TEST_HOST_ROOT=/path/to/hermes-agent`. Without it the
real-host case skips. The integration test uses a disposable profile and never
runs a job or calls a provider.

A Cron `ok` is not automatically a wake, selected focus, completed action or
delivered message. Natural use requires separate evidence through source
selection, native execution, canonical receipt and visible speech or silence.

## Maintenance

For each Hermes release, verify Cron create/edit syntax, native preflight,
session-origin persistence, PATH and canonical DB binding. Repeat an isolated
install/upgrade regression; update this list with exact Core/host refs and
the proven layer. Keep provider adapters separate from capabilities and
conversation channels. Do not equate another plugin's tests with Core support.

Installation rollback is not fully automatic: a failure after Cron mutation
can leave a job changed. Preserve the original job/DB configuration during an
upgrade; the known hardening item is recorded in [PLAN.md](PLAN.md).

## Documentation

- [AI_START_HERE.md](AI_START_HERE.md): short agent entry.
- [Architecture](skills/attention-steward/references/architecture.md):
  owner contracts and one-to-one acceptance.
- [Chinese architecture guide](docs/zh-architecture-guide.md) and
  [mobile PDF](output/pdf/Hermes-Attention-Core-中文架构说明.pdf).
- [PROGRESS.md](PROGRESS.md): dated tests and maintenance.
- [REQUIREMENTS.md](REQUIREMENTS.md), [SCHEMA.md](SCHEMA.md) and
  [PLAN.md](PLAN.md): behavior, storage and remaining work.

## License

[MIT](LICENSE).
