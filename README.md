# Hermes Attention Core

A portable, channel-neutral attention layer for a single owner-operated Hermes
Agent. It helps a live Agent notice external facts, reminders, continuations,
and meaningful task changes without replacing Hermes's conversation context,
voice, tools, MCP manager, or plugins.

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
  one exact source—or closes one exact full set as reviewed-quiet—then decides
  fresh action, speech, or silence.

The full reproducible contract is in
[architecture.md](skills/attention-steward/references/architecture.md).

## Install

```bash
git clone https://github.com/Aryuan026/HermesAttentionCore.git
cd HermesAttentionCore
python3 scripts/install_hermes.py --install-cron --deliver <platform>
```

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
