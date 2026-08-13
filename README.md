# Hermes Attention Core

**Give Hermes a sense of what matters next.**

A portable, channel-neutral attention layer for a single owner-operated Hermes
Agent. It helps a live Agent notice external facts, reminders, continuations,
and meaningful task changes without replacing Hermes's conversation context,
voice, tools, MCP manager, or plugins.

Instead of waiting for another direct command—or interrupting you for every new
event—Hermes can wake with a small, well-shaped field of possibilities, notice
the one thing that deserves care, use the abilities it already has, and respond
freshly. Sometimes the right result is an action. Sometimes it is a message.
Sometimes it is an auditable decision to stay quiet.

```text
external facts → Inbox adapters ┐
explicit future intent → stores ├→ one bounded attention set → live Hermes
                                 │                              │
Hermes native tools and MCPs ────┴──── discovered only as needed┘
```

The central boundary is simple:

- Conversation channels such as QQ, mobile, Feishu, or CLI are replaceable
  mouths. Ordinary turns do not become Attention events.
- External systems such as an AI forum, monitored mailbox, signup site, or
  sensor write compact facts through the generic Inbox adapter contract.
- Actual abilities remain native Hermes tools/MCP/plugins. Attention carries
  only optional broad domain hints, never tool schemas or permissions.
- A native Cron preflight wakes the normal foreground Agent. That Agent chooses
  one exact source plus the discrete meaning it actually saw—or closes only
  the bounded review it actually considered—then decides fresh action, speech,
  or silence.

The full reproducible contract is in
[architecture.md](skills/attention-steward/references/architecture.md).

## Why it fits Hermes

Hermes already knows how to converse, keep a live context, load Skills, and
call native tools or MCP servers. This project does not replace those parts.
It adds the missing **attention plane** between “something may matter” and
“wake the live Agent and let it decide what to do now.”

| Compared with | That layer answers | Hermes Attention Core answers |
|---|---|---|
| Hermes native tools / MCP / plugins | “What hands and abilities are available?” | “Which one situation deserves a bounded look now?” It leaves discovery, schemas, permission, and execution in Hermes. |
| Cron or reminder delivery | “What should run or be delivered at this time?” | “Should the live Agent wake and reconsider the current situation?” Stored text is context, never a frozen final message. |
| Queue / inbox worker | “Which queued job should execute next?” | “What would a person notice among reminders, continuations, tasks, and outside facts?” It is not FIFO and may mark one exact, fully shown review as quiet. |
| Event bus / notification system | “Which events should be transported to consumers?” | “Which compact facts remain salient after coalescing, expiry, diversity, and owner-aware judgment?” Not every event becomes speech. |
| Agent memory / chat history | “What past information can be recalled?” | “What needs a present look?” It neither copies the memory layer nor mines every conversation turn into a task. |
| Autonomous loop / workflow engine | “Which predefined action or next node runs?” | “Is one live decision worth making?” The foreground Agent still chooses a native capability, action, fresh reply, or silence. |

The core uses a unified Attention Opportunity Set: heterogeneous owner
candidates share one queue, provider priority remains a small 4% hint, and
selection uses an exact claim. The full eligible queue has a stable identity;
the smaller, fully displayed review has its own identity. A genuinely
uninteresting review can be closed exactly as `reviewed-quiet` without signing
off on hidden candidates. A selected focus also carries that review meaning
through pre-action validation, so a warning cannot silently become overdue
authority. The result is a compact portable layer that can give
an otherwise blank Hermes installation useful initiative without forcing a
new persona, memory system, conversation channel, or tool stack on it.

### Distinctive characteristics

- **Stimulus, capability, and mouth are separate.** External facts enter
  Inbox; abilities stay in Hermes; QQ, mobile, Feishu, CLI, or a future UI are
  interchangeable conversation surfaces.
- **Attention is human-shaped but auditable.** Due reminders have a direct
  lane; other candidates use bounded scoring, aging, provider/subject diversity,
  exact claims, and canonical receipts instead of an opaque free-running loop.
- **Silence is a real, evidenced decision.** `reviewed-quiet` closes exactly
  the bounded candidates whose full content the Agent received. It prevents
  repeat wakes for reviewed facts without pretending unseen facts were judged.
- **Interrupted work does not silently disappear.** Heartbeat recovers expired
  focus leases before rebuilding attention. A newer coalesced fact also makes
  an older claimed fact fail freshness validation before a side effect can be
  recorded as canonical success.
- **Identity does not drift with mood or time.** Scores may age and rankings may
  cross, but immutable source membership—not display order—defines `set_id`.
- **Tools appear progressively.** Attention supplies at most a broad domain
  hint. Hermes's own `tool_search` / `tool_describe` / `tool_call` path exposes
  only the concrete native capability needed for this turn.
- **New integrations do not grow the core sideways.** A forum, mailbox, signup
  site, sensor, or game provides compact idempotent events through an Inbox
  adapter. If it also offers actions, those are installed independently as a
  native MCP or tool. Inbox itself enforces payload bounds and secret
  sanitization instead of trusting every adapter to remember them.
- **Wakeup is not delivery.** Heartbeat only performs bounded preflight and
  asks native Cron to wake the normal Agent. The Agent judges, acts, and writes
  fresh speech—or stays silent—using its current context.

### Where it shines

- A research or community Agent notices a new forum question, then uses its
  existing knowledge and reply MCP only when the question merits attention.
- A monitored mailbox or student signup site contributes compact facts without
  turning every inbound record into an urgent interruption.
- A personal Agent remembers a deliberately deferred continuation and returns
  to it at a useful moment, with the causal context still attached.
- A maintenance Agent notices a meaningful state change in standing or periodic
  work while routine polling noise stays out of the foreground.
- A creative or simulation-connected Agent can occasionally inspect its world
  and choose an available native action without hard-coding that action into
  the scheduler.

### 中文速览

它想给 Hermes 增加的，是一种很轻的“惦念感”：不必每件事都由人明文下令，也
不会每来一条外部消息就立刻打断。日历、延续事项、任务变化和外部 Inbox 事实会
被收成一小盘候选；真正醒来的仍是活的前台 Agent，它当场决定使用哪个原生工具、
做什么、说什么，或者保持安静。QQ、mobile、飞书或未来的新入口都可以继续做它
的嘴；新 MCP 继续做它的手。Attention 只帮它判断——**此刻，什么值得看一眼？**

## Install

```bash
git clone https://github.com/Aryuan026/HermesAttentionCore.git
cd HermesAttentionCore
python3 scripts/install_hermes.py --install-cron --deliver <platform>
```

The installer pins one canonical database into both installed entrypoints. If
the database lives outside the default Hermes home, name it explicitly on every
install or upgrade:

```bash
python3 scripts/install_hermes.py \
  --attention-db /absolute/private/attention.sqlite3 \
  --install-cron --deliver <platform>
```

The installed CLI and heartbeat then use that same file even when their parent
processes have different environments. The CLI and heartbeat refuse to invent
a fallback database when this binding is absent.

If people will reply to heartbeat messages, keep those deliveries in the
target native conversation:

```bash
python3 scripts/install_hermes.py \
  --install-cron --deliver <platform> \
  --attach-to-session \
  --origin-platform <platform> \
  --origin-chat-id <native-chat-id>
```

Hermes mirrors each successful delivery into that foreground session, so a
follow-up such as “what arrived?” can refer to the event and action that just
happened. Changing QQ to mobile, Feishu, or another channel does not change the
Attention architecture; only rebind this native Cron origin when continuity is
wanted in the new mouth.

The installer probes Hermes's installed native Cron read/update seam and
verifies the persisted binding. If an upstream Hermes release moved that API,
installation fails with a compatibility error instead of reporting a false
success. The probe runs before the installer creates or edits the real
heartbeat job.

For a per-user-isolated group session, also pass the channel-native
`--origin-user-id`; add `--origin-thread-id` when the conversation is scoped to
a topic or thread.

The installer owns only the generic runtime package and three generic Skills.
It does not enable, disable, enumerate, or copy native capabilities. Re-running
it removes retired files from those owned trees without deleting independent
provider extensions.

## Connect an external AI forum

Read [the Inbox adapter contract](skills/attention-runtime-setup/references/external-inbox-adapters.md).
An adapter exposes `build_poll(stores)`, maps bounded records to `AgentEvent`,
commits through `stores.inbox.ingest()`, then ACKs upstream. Register the trusted
module with:

```bash
hermes-attention adapters register \
  --name ai-forum --module my_forum_attention
```

If Hermes may reply to the forum, register that ability separately through
Hermes's native MCP/tool path. The event feed itself grants no reply authority.

## Verify

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m unittest discover -s tests -v
```

Python 3.9+ is supported. Runtime databases, credentials, logs, chat text, and
receipts are excluded from Git.

## License

MIT.
