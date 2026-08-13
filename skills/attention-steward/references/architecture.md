# Hermes Attention Runtime — architecture handoff

This is the reproducible product contract for humans and agents. The short
version is: **Attention decides what deserves one live look; Hermes's own tool
system decides what hands are available; the foreground Agent decides what to
do and what to say.**

## 1. The whole picture

```text
External facts                         Foreground conversations
(AI forum, mail, forms, sensors)       (QQ, mobile, Feishu, CLI, future UI)
        │                                           │
        ▼                                           ▼
provider adapter → InboxStore             ordinary Hermes context
        │                                  explicit future intention only
        │                                           │
        └────────────┐                 arrange → Calendar / Task / Continuation
                     ▼                                │
              candidate adapters ◀───────────────────┘
                     │
              AttentionCoordinator
        unified set + 4% priority hint + diversity
                     │
empty pool → bounded routine-presence cadence
                     │
               native Cron wake gate
                     ▼
             live foreground Hermes Agent
                │                 │
        select/exact-claim        │ progressive native discovery
                │                 ▼
                │       Hermes toolsets + Hermes MCP manager
                │                 │
                └──── act / observe canonical receipt
                                  │
                         decide speech or silence now
                                  ▼
                    whichever conversation channel is active
```

There is no channel-specific Attention path, no provider-specific Attention
source kind, and no project-owned delivery layer.

## 2. One-to-one product requirements

| Required quality | Concrete implementation | Acceptance proof |
|---|---|---|
| Tool consolidation | The Agent sees one human-shaped loop: notice → judge → open one focus or close one exact review → find one hand → validate → act/observe → close → speak/silence. Poll, ACK, coalesce, leases, generations, and owner tables stay behind adapters/stores. | The wake Skill exposes `focus open/validate/close/defer/quiet-set`, not a bag of polling and database commands. |
| Human-like attention and decisions | Calendar direct lane handles true due reminders. Other owners merge into one AOS. Ranking uses urgency 34%, owner impact 25%, continuity 18%, freshness 11%, aging 8%, and provider priority only 4%; provider and subject diversity prevent one feed dominating. Full eligible membership and bounded fully shown review membership have separate identities. Review identity also binds discrete presented semantics such as warning/overdue, never continuous scores. The model may exact-claim one presented source/meaning, or close only the exact review it actually considered. | Tests assert weights, diversity, direct lane, exact claim, canonical score-independent set identity, warning→overdue rejection before claim and before action, review-scoped quiet CAS, hidden candidates remaining eligible, and no repeat wake for reviewed members. |
| Free attention without invented work | An empty AOS may open one throttled `routine_presence` wake. The packet carries only empty/populated state and reason; it does not manufacture a candidate or enumerate possible actions. The foreground Agent may use current context and native capabilities, speak, act, or remain silent. | Tests prove a real empty wake, no Attention payload or action menu, a bounded 24-hour wake budget, sleep-window coalescing, and unchanged immediate populated wakes. |
| Pluggability | External providers implement `external event → agent_event.v1 → InboxStore`. Capability providers do not implement an Attention interface at all: they register through Hermes native tools/MCP. New internal owners require an explicit product/schema change rather than an untested generic hook. | A generic fake provider reaches AOS without changing scoring; a newly registered MCP requires no Attention-core edit. |
| Adaptability | Channels are replaceable mouths. Conversations remain their native context; only explicit arrange actions form Calendar/Task/Continuation state. Candidate `capability_hints` are broad optional domains, never tool IDs or permissions. | Negative tests show QQ/mobile text is not ingested, and an event still wakes when its suggested MCP is absent. |
| Portability | The runtime uses standard-library Python, a private SQLite file with owner-separated tables, generic setup/arrange/steward Skills, and one canonical Cron in normal Agent mode. Provider extensions are separate installable modules. | Blank-home installer test, Skill validation, upgrade test from legacy hook/no-agent Cron. |
| Native capability compatibility | Actual actions always go through Hermes's enabled platform toolsets and MCP registry. The runtime neither mirrors every tool schema nor narrows Hermes to an Attention whitelist. Discovery starts with domain hints and expands only the minimum capability needed for this turn. | With every optional adapter removed, native tools remain untouched; provider poll/ACK never become model tools. |

If any row fails, the architecture is not Green; repair it rather than adding a
compatibility fallback.

## 3. Owners and responsibilities

| Owner | Writes | Attention may do |
|---|---|---|
| `InboxStore` | Idempotent external events, enforced bounds/sanitization, coalesce/supersede, expiry, exact claims | Read due candidates and route exact claim/settlement back |
| `CalendarStore` | Explicit reminders and their context | Read due item as a direct trigger; never turn the note into final speech |
| `ContinuationStore` | A causal intention deliberately deferred to a later stage/time | Read all due continuations and route exact claim |
| `TaskStore` | Scheduled, standing, periodic tasks plus separate cycle history | Read meaningful task transitions; never run task maintenance inside AOS build |
| `AttentionCoordinator` | No source-table SQL; cross-owner transaction orchestration through Store APIs | Build a deterministic view, preserve canonical full eligible identity, bound a separately identified review, and route exact lifecycle operations |
| `PresenceCadenceStore` | One next-eligible timestamp and cadence generation | Open a bounded empty-pool foreground opportunity; never create an AOS member or prescribe an action |
| Provider adapter | Poll one external source and ACK only after canonical Inbox ingest | Nothing else |
| Hermes native capability manager | Enabled toolsets, MCP servers, schemas, platform policy, execution | Remains fully authoritative |
| Live foreground Agent | Current judgment, capability choice, action, speech/silence | May exact-claim one source plus its presented review version, freshness/semantics-validate before action, or turn none into an exact bounded-review quiet terminal; reports only canonical outcomes |

Sharing one SQLite file is a deployment convenience, not shared ownership.
The installer binds both model-facing CLI operations and heartbeat preflight to
the same canonical path. A custom deployment path is explicit installation
state; neither entrypoint silently falls back to a second home-directory file.

## 4. External adapter contract

Every forum/mail/form/sensor adapter maps provider vocabulary to the same
safe event fields: stable provider and event IDs, event kind, compact payload,
source references, subject/coalesce/follow-up keys, event and expiry times,
bounded priority hint, and optional broad capability domains.

The Store enforces payload depth/node/container/byte limits, reference and hint
counts, and secret sanitization. This is a trust boundary, not only an adapter
authoring recommendation.
Stable identity and routing fields reject overlength input; unlike display
text, they are never truncated into possible aliases.

The ordering is strict:

```text
poll → validate and sanitize → idempotent Inbox commit → upstream ACK
```

If commit fails, ACK must not happen. Provider prose is context only; ingestion
does not grant action, memory writing, notification, or tool permission.

An external AI forum adapter therefore writes new-thread or new-reply facts to
Inbox. If the Agent can reply, that separate ability is registered through
Hermes MCP; the adapter itself grants no reply authority.

## 5. Tasks without flooding attention

The repaired runtime preserves Hermes's useful task ideas while moving them to
the correct owner boundary:

| Hermes task idea | Repaired correspondence | Why |
|---|---|---|
| Scheduled one-shot warning, grace, expired | `TaskStore` computes `warning`, `overdue`, and `expired` from stored due/warn/grace values | Keeps real time semantics without making every task urgent |
| Standing/permanent work | An active task with optional form, pin, block, and `next_check` | Durable work survives one attention look |
| Monthly work | A periodic definition plus one concrete `hermes_task_cycles` row per month | Old cycles and results are never overwritten |
| Periodic generator | `TaskStore.maintain()` creates cycles before AOS build | The generator is maintenance, not a candidate competing for attention |
| Task candidates | `TaskCandidates` reads meaningful current transitions only | AOS remains read-only and heartbeat noise stays bounded |
| Completion forms/history | Form schema lives on the task; each cycle stores its own result and terminal time | Humans and agents can audit what happened in each period |
| Timezone | Explicit value, default `Asia/Shanghai` | Monthly and due semantics do not depend on host timezone |
| Due proximity | Converted into this task candidate's urgency only | It does not invent a new global AOS weight |
| Provider priority | Restored to exactly 4% globally | Task tuning cannot silently rewrite attention policy |

Standing work appears when new, changed, blocked, pinned, when `next_check`
becomes due, or when a new cycle begins—not on every heartbeat.

## 6. Progressive capability exposure

Attention does not enumerate all capabilities. A candidate may say only that a
situation resembles `leisure`, `work`, `world`, `relationship`, or another
broad domain. The live Agent then uses the capability facilities already
provided by its Hermes session:

1. infer the likely domain;
2. let Hermes keep core tools present; when its configured MCP/plugin schemas
   cross the native threshold, use its own `tool_search` bridge;
3. call native `tool_describe` only for the minimum concrete tools needed;
4. execute a deferred tool through native `tool_call` (or call an already
   present core tool normally);
5. trust only canonical receipts;
6. decide whether further action or speech helps.

An absent suggested MCP is a true unavailable capability, not a reason to
cancel the wake or disable native tools. Adding a new MCP changes Hermes MCP
configuration and perhaps a domain Skill; it does not change Inbox schema,
AOS scoring, or the heartbeat.

### Exactly what the Agent sees

| Surface | Model-facing operations | Not exposed |
|---|---|---|
| `attention-arrange` | Arrange a reminder, continuation, or scheduled/standing/periodic task, update meaningful task state, and complete a periodic cycle from an explicit foreground intention | Raw chat capture, automatic intent mining, database tables |
| `attention-steward` | Open one exact focus; validate freshness; close it honestly; defer it into one continuation; or quiet one exact bounded review | FIFO claim-next, lease renewal, source polling, coalesce, migration |
| Hermes native capability layer | Enabled core toolsets plus Hermes's own progressive `tool_search` / `tool_describe` / `tool_call` bridge for large MCP/plugin surfaces | An Attention-owned copy of all tools or a project whitelist |
| Provider adapters | Nothing directly; their compact facts appear as Inbox-derived context | Transport commands, secrets, ACK controls, raw provider payloads |

Thus a future mail MCP may supply actions through Hermes while a separate mail
watcher supplies events through Inbox. Either side can exist without the
other, and neither requires a new Attention tool family.

## 7. Wake and speech semantics

The heartbeat script is a preflight, not an agent and not a delivery service.
It polls adapters, recovers expired source claims, runs task maintenance
outside AOS, builds the direct/AOS packet, and ends with Hermes Cron's
`wakeAgent` gate. Recovery happens before candidate building so a process crash
cannot leave an owner’s only candidate permanently invisible.

When a populated pool makes the gate true, native Cron starts its normal Agent
with normal tools and current context. The Agent makes a fresh decision, acts
if useful, then writes fresh speech—or deliberately stays silent. Stored
reminder text, provider text, prior replies, and script stdout never become an
alarm-style final message.

An empty pool follows a separate cadence adapted from Asherie Home's routine
presence wheel: a default 2-hour minimum gap plus up to 1 hour of stable jitter,
with the 01:00–08:00 local sleep window coalesced into one later morning chance.
Unlike Home, the portable runtime does not inspect any channel's human-message
timestamps; the cadence is anchored only by its own foreground wakes, so QQ,
mobile, Feishu, and future channels remain replaceable mouths. The empty packet
contains only `pool_state: empty` and its cadence reason. Inclinations such as
“playing is allowed” belong to SOUL/memory/domain Skills and available native
capabilities—not a permanent task row or an action menu in the heartbeat.
Opening a selected focus compares the immutable source version and the bounded
review's discrete `review_version`, then stores both meanings with the claim.
Validation and terminal settlement compare them again. A warning-phase decision
cannot cross into overdue execution even though the underlying task source
version—and therefore stable set identity—has not changed.

For a conversational heartbeat, the deployment may opt into Hermes's native
`attach_to_session` behavior and bind the job to one channel origin. After a
successful delivery, Hermes mirrors that fresh result into the matching native
foreground session, so the next human reply retains causal context. This is a
Cron/session configuration seam—not an Attention owner, Inbox event, transcript
adapter, or project delivery implementation. Changing channels only requires
rebinding the native origin. Installation probes Hermes's actual
`get_job/update_job` API and verifies persisted state after update; incompatible
upstream versions fail visibly instead of passing on a fake interface. Attach
mode runs the compatibility probe before any heartbeat job create/edit.

## 8. Migration and forbidden regressions

Upgrade disables the legacy `attention-transcript` hook and converts the
canonical heartbeat from `no-agent` to normal Agent mode. Legacy tables remain
available for audit; settled provider history is not replayed, pending chat rows
are not guessed into tasks, and pending continuations are migrated only when
their semantics are explicit.

Do not reintroduce:

- channel-specific transcript ingestion;
- provider events mapped to a bespoke Attention owner instead of Inbox;
- a script that launches `hermes -z` or prints final owner speech;
- direct delivery/projection code;
- AOS mutation, task maintenance, FIFO fallback, or hidden second owner;
- score/ranking order participating in set identity;
- continuously changing scores participating in review identity;
- quieting a new task phase from an older review version;
- claiming or acting on a new task phase from an older review version;
- reviewed-quiet receipts for candidates whose full content was not shown;
- expired claims remaining invisible until an unrelated claim attempt;
- provider poll/ACK tools exposed to the model;
- an Attention-owned tool registry or all-tools whitelist;
- success claims without canonical receipt and visible end-state evidence.
