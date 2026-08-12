---
name: attention-arrange
description: Turn an explicit future intention from any foreground Hermes conversation into the correct Calendar, Task, or Continuation owner. Use when the owner asks for a reminder, establishes ongoing work, or deliberately wants the current thread resumed later; do not use on ordinary chatter.
---

# Attention Arrange

Conversation channels are mouths, not event feeds. Keep ordinary QQ, mobile,
Feishu, CLI, and future-channel turns in Hermes's normal context.

Write future state only when the live conversation clearly forms one:

- A message should wake the Agent at a specified time: `hermes-attention
  arrange reminder`.
- A current causal thread should be reconsidered at a later stage: use
  `arrange continuation`.
- Durable work has its own lifecycle: use `arrange task` with `scheduled`,
  `standing`, or monthly `periodic` semantics.
- A real task change uses `arrange task-update` so changed, pinned, blocked, or
  due-for-check state can surface once without recreating the task.
- Finishing the current cycle of a periodic task uses `arrange task-complete`;
  do not settle or recreate the durable parent task.

Confirm the resulting owner ID in the current conversation. Do not copy the
whole transcript, a prior assistant reply, credentials, or private history into
the record. Store a compact goal/context and broad optional capability domain.

Never create future state merely because a message was recent, emotional,
interesting, or came from a group. If timing or intent is genuinely ambiguous,
ask naturally in the same foreground turn.
