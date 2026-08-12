---
name: attention-runtime-setup
description: Install, upgrade, repair, or verify the portable Hermes Attention Runtime and external Inbox adapters. Use on a blank Hermes, when changing conversation channels, adding an external event source such as an AI forum, or repairing the heartbeat architecture.
---

# Attention Runtime Setup

Read `../attention-steward/references/architecture.md` before changing the
runtime.

## Install or upgrade

1. Confirm `python3`, `git`, and `hermes` exist. Conversation delivery is a
   Hermes deployment choice, not an Attention data source.
2. Clone or update the runtime with the owner's existing GitHub authorization.
   Never request a pasted token.
3. Install or upgrade one canonical runtime and normal Agent Cron:

   ```bash
   python3 scripts/install_hermes.py --install-cron --deliver <platform>
   ```

   If people will reply to heartbeat messages, bind the job to that channel's
   native foreground session:

   ```bash
   python3 scripts/install_hermes.py \
     --install-cron --deliver <platform> \
     --attach-to-session \
     --origin-platform <platform> \
     --origin-chat-id <native-chat-id>
   ```

   Use channel-native IDs from the private deployment; never commit them.

Re-running updates the same heartbeat rather than creating another. The
installer refreshes only generic Attention Skills and moves the legacy
conversation-transcript hook out of active hooks. Native session binding also
probes Hermes's installed `cron.jobs.get_job/update_job` seam and fails closed
with a compatibility error when upstream moved it.

## Add integrations at the correct seam

- External facts: implement the adapter contract in
  [external-inbox-adapters.md](references/external-inbox-adapters.md), then
  register the trusted module with `hermes-attention adapters register`.
- New abilities: register them through Hermes's normal MCP, tool, or plugin
  setup. Do not put tool schemas or permissions in Attention.
- New conversation channel: connect it to Hermes normally. No Inbox adapter is
  required. Rebind the heartbeat origin only when its messages should be
  continuable in that new channel's foreground session.
- New domain guidance: add a narrow Skill only when tool descriptions do not
  explain enough; never attach every domain Skill to every heartbeat.

## Verify

- Empty preflight ends with `{"wakeAgent": false}` and sends no message.
- A due reminder or eligible set ends with `{"wakeAgent": true}` and wakes the
  normal Cron Agent.
- A fake provider event is idempotent, sanitized, and ACKed only after ingest.
- Claim one candidate, let its lease expire, then verify the next heartbeat
  recovers it before build.
- More eligible items than the review window leaves unseen items pending after
  a successful reviewed-quiet close.
- The wake packet includes provider/event/source references as context, while
  capability hints remain non-authoritative broad domains.
- Ordinary conversation produces no Inbox row unless the foreground Agent
  deliberately arranges future state.
- Native tools remain available with every optional adapter removed.
- An adapter failure is visible but does not block another due owner.
- A reported action has a canonical tool receipt and a settled focus.
- A reply to a conversational heartbeat sees the mirrored delivery in the
  native channel session; no channel transcript was copied into Inbox.
