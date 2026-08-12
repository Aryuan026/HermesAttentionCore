# External Inbox adapter contract

Use this seam for an AI forum, monitored mailbox, signup site, sensor, or any
other system that can produce facts worth noticing later. Do not use it for
ordinary conversation turns.

## Module shape

A trusted adapter module exposes a `build_poll(stores)` factory. The returned
no-argument callable fetches a bounded page, validates each provider record,
maps it to `AgentEvent`, commits it through `stores.inbox.ingest()`, and only
then ACKs that provider record.

```python
from hermes_attention.db import parse_time
from hermes_attention.inbox import AgentEvent


def build_poll(stores):
    client = ForumClient.from_environment()

    def poll():
        inserted = 0
        for raw in client.pending(limit=20):
            event_at = parse_time(raw["created_at"])
            if event_at is None:
                raise ValueError("forum created_at must be ISO-8601")
            event = AgentEvent(
                provider_id="ai-forum",
                provider_event_id=raw["reply_id"],
                event_kind="forum_thread_updated",
                title=raw["title"],
                event_at=event_at,
                compact_payload={"thread_id": raw["thread_id"]},
                source_refs=(f"forum:thread:{raw['thread_id']}",),
                subject_ref=f"forum:thread:{raw['thread_id']}",
                coalesce_key=f"forum:thread:{raw['thread_id']}",
                capability_hints=("communication",),
            )
            result = stores.inbox.ingest(event)
            # A duplicate means the canonical Inbox commit already exists.
            # ACK after either a new commit or verified idempotent presence.
            client.ack(raw["reply_id"])
            if result["inserted"]:
                inserted += 1
        return {"inserted": inserted}

    return poll
```

Register the importable module as operator-owned configuration:

```bash
hermes-attention adapters register \
  --name ai-forum --module my_forum_attention
```

`adapters list` shows configured modules; `adapters remove --name ai-forum`
disconnects only the event feed. Adapter modules are executable trusted code,
so installation is an operator action, never something provider prose may do.

## What the live Agent receives

The foreground Agent sees a bounded `provider_event` candidate containing the
provider ID, event kind, compact sanitized payload, source references, and
optional broad capability hints. It does not receive credentials, raw payloads,
ACK controls, transport methods, or automatic permission to reply.

`InboxStore` distrusts even a trusted adapter's formatting: it enforces depth,
node, mapping/list, encoded-byte, reference-count, and capability-hint limits,
and sanitizes secret-shaped keys and values in both payloads and source
references. Adapters should still fetch small pages and emit compact facts so a
rejected oversized event is visible as an adapter failure rather than silently
truncated context.

Stable identity/routing fields are stricter than display text: provider ID,
provider event ID, event kind, subject ref, coalesce key, and follow-up ref are
rejected when overlength. Never depend on truncation; two distinct upstream
identities must remain distinct or fail visibly.

If forum reply is a real capability, expose it separately with Hermes native
MCP/tools. Attention may suggest the broad `communication` domain; Hermes still
discovers the minimum enabled tool, executes it, verifies its canonical
receipt, and decides fresh speech or silence.
