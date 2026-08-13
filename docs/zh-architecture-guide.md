# 给 AI 一点“惦记感”

> Hermes Attention Core 中文架构说明<br>
> 面向人类读者，也面向接手代码的 AI Agent<br>
> 实现基线：公开仓代码提交 `783f81a`；文档日期：2026-08-13

手机友好的 3:4 图解版：
[`output/pdf/Hermes-Attention-Core-中文架构说明.pdf`](../output/pdf/Hermes-Attention-Core-中文架构说明.pdf)

## 先用一句话理解

Hermes Attention Core 不是第二个 AI、不是记忆库，也不是定时发送器。
它是一层轻量、可审计的“注意力”：把日历提醒、需要续上的事情、任务变化和外部
世界事件收成一小盘候选，然后唤醒**同一个活的前台 Agent**，让它当场决定看什么、
调用哪只原生“手”、说什么，或者保持安静。

```text
外部事实 → Adapter → Inbox ┐
明确的未来意图 → Calendar / Task / Continuation ├→ Attention set
                                                     ↓
                                              Hermes native Cron
                                                     ↓
                                              同一个前台 Agent
                                             ↙               ↘
                              Hermes native MCP/tools     当前对话上下文
                                             ↘               ↙
                                      新鲜行动 + 新鲜表达/沉默
```

## 为什么需要它

普通对话 Agent 很聪明，但大多数时候是“你叫它，它才动”；传统 Cron 能按时触发，
却常常只能把一段预写文字像闹钟一样甩出来。Attention Core 补的是两者中间的一层：

- Cron 只负责问：“现在是否值得把 Agent 叫醒？”
- Attention 只负责给出一盘有边界的候选。
- 真正的 Agent 仍用此刻的上下文重新判断、行动和表达。

因此，提醒文字是上下文，不是最终回复；外部事件是事实，不是行动命令。

## 三件事必须分开

| 层 | 它回答的问题 | 真实归属 |
|---|---|---|
| 刺激 stimulus | 有什么值得看一眼？ | Inbox、Calendar、Continuation、Task |
| 能力 capability | 我现在有哪些手可以用？ | Hermes 原生 tools、MCP、plugins |
| 嘴 mouth | 最后从哪里说话？ | QQ、mobile、飞书、CLI 或未来渠道 |

换 QQ、mobile 或飞书，只是换嘴；添加论坛、邮箱或报名网站，是增加 Inbox adapter；
增加回复论坛、查知识库或操作业务的能力，是增加 Hermes MCP/tool。三条线互不冒充。

## 一次注意力是怎样发生的

1. **后台维护**：轮询可信 adapter、恢复过期 claim、维护周期任务；这些动作不进入
   模型的工具袋。
2. **日历直达**：真正到期的 Calendar 提醒走 direct lane，不和普通候选抢排名。
3. **统一候选**：Continuation、Task、Inbox 进入同一个
   `attention_opportunity_set.v1`。
4. **像人一样收拢**：评分由 urgency 34%、owner impact 25%、continuity 18%、
   freshness 11%、aging 8%、provider priority 4% 组成，并做 provider/subject
   diversity；外部消息不会因为“刚到”就自动成为第一优先。
5. **只展示一小盘**：模型最多看到 bounded review（默认 12 条）的完整内容；隐藏候选
   仍留在队列，不能被模型代签“我看过了”。
6. **只开一个 focus**：模型 exact-claim 一条候选，或把自己完整看过的这一小盘
   `reviewed-quiet`。
7. **渐进找手**：从 broad capability hint 推断领域，再用 Hermes 原生
   `tool_search → tool_describe → tool_call` 找到最小所需能力。
8. **行动前复核**：`focus validate` 再检查 lease、source version、review semantics
   和 supersede 状态。
9. **诚实收尾**：只有 canonical receipt 才能证明做成；Agent 根据真实结果决定现在
   说什么或保持沉默。

## 身份为什么分三层

这是实现里最重要、也最容易写错的部分。

| 标识 | 绑定什么 | 不能绑定什么 |
|---|---|---|
| `source_version` | 事实本身的稳定版本 | 随时间变化的评分 |
| `set_id` | 全部合法候选的 canonical membership | 排名顺序、freshness |
| `review_id` + `review_version` | 本轮真正展示的候选及离散语义，例如 `warning/overdue` | 连续变化的 due proximity |

例子：模型 09:59 看到一个任务是 `warning`，10:00 任务变成 `overdue`。事实 ID 可以
没变，但判断语义已经变了。旧 `review_version` 不能在 10:01 授权 quiet、claim 或
side effect；系统必须返回 `semantic_changed`，让 Agent 重新看。

同时，claim 有 lease。Agent 崩溃后，heartbeat 会在下一轮 build 前恢复过期 claim，
避免唯一候选永久隐身。一个 Inbox 事实若被更新状态 coalesce/supersede，旧 claim
也不能写下“成功行动”的 receipt。

## 四个 owner，一张数据库

SQLite 文件可以共享，但表的写入权不共享：

- `InboxStore`：外部事实、幂等、清洗、边界、coalesce、supersede、expiry。
- `CalendarStore`：明确提醒与 direct lane。
- `ContinuationStore`：有因果关系、明确延后的下一阶段。
- `TaskStore`：scheduled、standing、periodic，以及独立 cycle 历史。
- `AttentionCoordinator`：只构建统一视图并编排事务，不直接成为 source row 的 owner。
- `source_receipts`：终局结果与最小可审计证据。

`TaskStore.maintain()` 在 AOS build 之前运行；维护动作本身不是“值得注意的事情”。
周期任务每个周期有独立 row，旧结果不会被下个月覆盖。

## 三种扩展，各走自己的门

### 接一个外部信息源

实现 `external record → AgentEvent → InboxStore.ingest()`；canonical commit 成功后
才能 ACK 上游。Adapter 失败可以被观察，但不能挡住别的 owner 的到期事项。

### 接一个新能力

照常注册 Hermes MCP/tool/plugin。Attention 只携带 broad domain hint，不复制所有
schema、不授予权限，也不维护项目白名单。

### 接一个新对话渠道

照常接入 Hermes。需要 heartbeat 后续对话连续性时，重绑 native Cron origin；不要
新增一个 channel-specific Attention owner，更不要把群聊全文塞进 Inbox。

## AI 接手代码时看哪里

```text
src/hermes_attention/
  runtime.py        heartbeat 维护顺序、wake gate、cron packet
  attention.py      Candidate、评分、set/review identity、Coordinator
  claims.py         exact claim、lease、review_version、settle
  inbox.py          外部事件边界、清洗、幂等、coalesce/supersede
  calendar.py       direct reminder owner
  continuations.py  因果延续事项 owner
  tasks.py          scheduled/standing/periodic 与 cycle
  db.py             SQLite schema、事务与文件权限
  adapters.py       可信 adapter 注册与隔离轮询
  cli.py            arrange/build/focus 的模型操作面

scripts/
  hermes_attention_heartbeat.py  只做 preflight，不生成最终回复
  install_hermes.py              安装、升级、唯一 DB 路径、Cron
```

安装器把 CLI 与 heartbeat 同时钉到一个 `HERMES_ATTENTION_DB`。如果使用自定义路径，
每次安装/升级都显式传 `--attention-db`；任一入口缺少绑定都会明确失败，不会在默认
目录偷偷生成第二本账。

## 模型真正能看到的操作

```text
focus open      精确打开一条已展示候选
focus validate  行动前检查它仍然新鲜、仍是同一个语义
focus close     用 canonical 结果收尾
focus defer     原子地关闭当前 focus，并建立一条 continuation
focus quiet-set 只关闭这一轮完整看过的 bounded review
```

模型看不到 provider ACK、数据库迁移、claim-next、原始传输 payload 或 Attention 自己
复制的一整套工具注册表。

## 它不是什么

- 不是记忆系统：它可以提示“值得回想”，但不取代 Hermes 的记忆层。
- 不是自动任务执行器：它唤醒真实 Agent，由 Agent 当场判断。
- 不是消息投递器：heartbeat 不写预制回复，渠道仍属于 Hermes。
- 不是工具代理层：MCP/tool 的权限和 schema 仍由 Hermes 管理。
- 不是“所有消息都马上处理”：Inbox 事实只获得被考虑的机会。

## 当前验证口径

公开实现的回归覆盖：owner 分离、adapter 失败隔离、外部输入清洗、direct lane、评分与
diversity、stable set identity、bounded reviewed-quiet、warning→overdue 语义变化、
lease recovery、superseded freshness、atomic receipt、channel negative、native tool
boundary、安装升级和单一数据库绑定。

代码 Green 不冒充真实行为 Green。真实链路仍按以下阶段报告：

```text
available → delivered → selected → requested → executor_started
→ canonical_receipt → visible_projection_or_deliberate_silence
```

## 冷启动最短路线

1. 先读根目录 [`AI_START_HERE.md`](../AI_START_HERE.md)。
2. 再读 canonical contract：
   [`skills/attention-steward/references/architecture.md`](../skills/attention-steward/references/architecture.md)。
3. 对照 [`REQUIREMENTS.md`](../REQUIREMENTS.md)、[`SCHEMA.md`](../SCHEMA.md) 和上面的
   code map。
4. 修改后运行：`PYTHONPATH=src python3 -m unittest discover -s tests -v`。

项目地址：<https://github.com/Aryuan026/HermesAttentionCore>
