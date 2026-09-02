# AgentFlow 后续开发计划

架构与数据模型见 [architecture.md](architecture.md) 与 [data-model.md](data-model.md)。

**最后核对：** 2026-09-02

## 优化方向

按投入产出比排序：

1. ~~**事件总线持久化。**~~ 已用 Redis Stream `agentflow:run:{run_id}:log` 做 durable replay；pub/sub 仍负责 live 投递；支持 `Last-Event-ID` 重放。
2. **队列 / LLM / Run OTel 指标与背压。** 深度/消费者延迟已导出为 `agentflow.queue.*`；worker 利用率见 `agentflow.worker.utilization`；LLM token/cost、Run 结局、Step/ToolCall RED 见 `agentflow.llm.*` / `agentflow.run.outcomes` / `agentflow.step.*` / `agentflow.tool.*`；面板见 `docker/grafana/dashboards/agentflow-observability.json`。
3. **控制台调试体验。** Step 可视化时间线、独立 ToolCall 检查面板。
4. ~~**LangGraph adapter 扩展。**~~ 更多 graph 模式、MCP 工具协议集成（`mcp` adapter + `AdapterToolSurface` bridge）。
5. **双向流式传输。** WebSocket / WebTransport + SSE 降级，支持双向取消与审批。
6. **Agent Memory。** 先瘦身 Run 级 Message/Checkpoint，再加 Thread 与语义记忆；详见下方专项。

## 可引入的先进技术

| 领域 | 候选方案 | 价值 |
| --- | --- | --- |
| 长任务编排 | Temporal、Restate | 超越 Redis ACK 的 durable timer、saga、人工审批 |
| LLM 可观测 | Langfuse、Arize Phoenix、OTel GenAI | 在现有 Step/Message 之上做 trace 与 eval |
| 工具协议 | MCP | 标准化 adapter 工具面 |
| 向量 / 记忆 | pgvector（首选，与现有 Postgres 同库）、可选 LanceDB | 语义检索与长期记忆；**不得**把记忆塞进某个 adapter 的 checkpointer |
| 认证与多租户 | OIDC + `tenant_id` | RBAC、审计、团队隔离 |
| SDK 生成 | OpenAPI → TS/Python | Java、FastAPI、前端类型自动同步 |
| 部署 | Helm、HPA | 将 compose profile 产品化 |

## 路线图

### Phase 2 收尾 — 可观测性与运行控制（2026 Q2）

**目标：** 控制台调试闭环、事件可靠性与运行时指标。

- [x] Step 时间线组件（节点延迟与状态流转）
- [x] 独立 ToolCall 检查面板（参数/结果/错误结构化浏览）
- [x] SSE 事件重放（`Last-Event-ID` / 持久化 event log）
- [x] 队列深度、worker 利用率导出为 OTel/Prometheus 指标
- [x] p95 耗时仪表盘与告警
- [x] LLM token/cost、Run 成功率、Step/ToolCall 指标 + Grafana 面板
- [x] RunUsage 扩展：step/tool 计数（控制台列表与详情）

**验收：** 控制台展示可视化时间线；断连 SSE 可补全事件；队列指标可在 Grafana 查看。

### Phase 3 — 可扩展性与 SDK（2026 Q3）

**目标：** 第三方框架与工具可插拔，无需 fork runtime。

- [x] Adapter 插件注册表（entry points / 动态加载）
- [x] 官方 adapter：AutoGen、CrewAI、PydanticAI（按需求选 2 个；已完成 AutoGen + PydanticAI）
- [x] MCP tool adapter
- [x] OpenAPI 规范 + Python/TypeScript SDK 自动生成
- [ ] Webhook 出站事件（`run.completed` 等）
- [x] Agent 版本管理与配置 diff

**验收：** 新 adapter 以包形式发布；SDK 覆盖 create-run + subscribe-events；MCP 调用写入 ToolCall。

### Phase 4 — 生产与企业能力（2026 Q4）

**目标：** 多租户安全部署、治理与长任务。

- [ ] OIDC 认证与服务账号 API Key
- [x] 简易 API Key 多租户 + RBAC（`tenant_id`、viewer/operator/admin；OIDC 仍待做）
- [x] RBAC：组织/项目/Agent 作用域
- [ ] cancel/resume 审计
- [ ] 人工审批 UI（`waiting_human` + 通知）
- [x] Temporal（或 Restate）集成超长 Run
- [ ] Helm + Terraform；按队列延迟自动扩缩 worker
- [ ] Agent 级 token/成本配额

**验收：** 双租户演示；审批门控生效；24h+ 工作流在 worker 重启后仍可恢复。

### Phase 5 — 智能层（2027）

**目标：** 在 runtime 之上提供 eval、记忆与路由，而非塞进 adapter。

- [ ] Run 对比与回归套件
- [ ] Agent 记忆服务（见下方专项；对话线程 + 情景摘要 + 语义事实 + 文档 RAG）
- [ ] 模型路由 / fallback 策略
- [ ] 定时与批量 Run
- [ ] 细粒度流式：推理块、多模态附件（DB 持久化）

## Agent Memory 专项

现状不是「记忆做了一半」，而是 **只有 Run 级 transcript / checkpoint，没有记忆子系统**。`Message` 和 `Checkpoint` 服务的是可观测性与失败恢复，不能跨 Run 回忆，也不能按语义检索。Phase 5 原先的「对话 + 文档存储」应拆成可落地的分层，而不是一次性大服务。

### 现状（代码事实）

| 已有 | 实际作用 | 缺口 |
| --- | --- | --- |
| `Message`（`backend/app/models/run.py`） | 单次 Run 内有序 transcript；`role` 为 system/user/assistant/tool | 无 `thread_id` / `user_id`；无跨 Run 查询；`content` 仅 TEXT；`GET /v1/runs/{id}` 一次拉全量 |
| `Checkpoint.state` | adapter 不透明快照，供 retry/resume/Temporal 恢复 | LangGraph 每次节点把整份 `graph_state`（含不断增长的 `messages`）写入 JSON；与 `Message` 行重复存储 |
| `AdapterContext`（`backend/app/adapters/base.py`） | 只写：`emit_message` / `emit_checkpoint` | 无 `recall` / `search` / `store`；adapter 看不到历史 Run |
| `POST /v1/runs` | 每次调用独立 Run | 无会话/线程；连续对话只能由客户端自己拼 `input` |
| 控制台 Messages 列表 | 按 `r.messages` 全量渲染 | 无折叠、无检索、无「从哪条记忆注入」的审计 |

LangGraph 默认图（`backend/app/adapters/langgraph_adapter.py`）把完整 `messages` 列表交给模型，没有窗口裁剪、摘要或 token 预算。retry 时 Java/Python 把 `checkpoint_state` 塞进 `Run.metadata._resume` 再入队 Redis——长对话会把大 JSON 打进 metadata 和 job payload。

设计原则（与 Phase 5 一致）：**记忆是 runtime 能力，adapter 只消费 API。** 不要用 LangGraph `MemorySaver` / AutoGen 内部 store 充当产品记忆，否则换 adapter 就丢记忆。

### 分层模型

```
L0  Working     当前 Run 的 Message + Checkpoint（已有，需治膨胀）
L1  Thread      同一 thread 下跨 Run 的短对话窗口（新增）
L2  Episodic    Run 结束后的情景摘要，按时间回忆「上次做了什么」（新增）
L3  Semantic    用户偏好、实体事实、文档切片；向量检索（新增）
L4  Procedural  成功工具轨迹 / 可复用计划（后置，可选）
```

L0 属于执行与审计；L1–L3 才是「Agent Memory」。L0 不能删，但必须停止把 L0 当长期记忆用。

作用域一律带 `tenant_id`，并支持 `project_id` / `agent_id` / `thread_id` / 可选 `user_id`。跨租户召回视为漏洞。

---

### 优化：先治现有 Working Memory（L0）

按投入产出比，这些可以在记忆服务上线前单独做，也能降低后续迁移成本。

1. **Checkpoint 与 Message 解耦。** 节点 checkpoint 只存图控制态（`completed_nodes`、`pending_human`、`route`、`reply` 指针），**不要**再拷贝整份 `messages`。恢复时从 `messages` 表重建窗口。入口：`langgraph_adapter.py` 的 `emit_checkpoint`、`_initial_graph_state`。
2. **Checkpoint 保留策略。** 默认只保留 latest + 人工审批点 + 失败前一拍；其余压缩或删。避免 Postgres JSON 与 `GET /v1/runs/{id}` 随节点数线性膨胀。入口：`run_service.py` `_handle_event("checkpoint.created")`。
3. **Retry payload 瘦身。** `_resume` 只带 `checkpoint_index`（及必要的小字段），worker 从 DB 读 `Checkpoint.state`，禁止把整份 graph_state 写入 `Run.metadata` 再经 Redis 传递。入口：Python/Java `retry_run` / `resume_run`、`resume_context.py`。
4. **LLM 上下文窗口。** LangGraph `agent`/`model` 节点在 `_invoke_model` 前做 token 预算：保留 system + 最近 N 轮，超出则先摘要再调用。配置项建议：`memory.window_tokens`、`memory.summarize`。无窗口管理时，长 Run 会同时烧 token 并撑爆 checkpoint。
5. **Message 分页与投影。** 新增 `GET /v1/runs/{id}/messages?cursor=&limit=`；`GET /v1/runs/{id}` 默认只带最近 K 条或省略 messages。控制台改为分页/虚拟列表。长对话的一次全量 hydrate 会拖垮 API 与前端。
6. **减少重复 emit。** `model` 节点每个 tick 都 `emit_message(system)` + `emit_message(user)`，transcript 被 system prompt 刷屏。改为 run 级一次 system，或标记 `extra.kind=prompt_echo` 供 UI 折叠。
7. ~~**`emit_message` 关联 `step_id`。**~~ 契约补 `step_index`，runtime 解析为 `step_id`；各 adapter 已传递；SSE/API `Message.step_id` 与控制台 Messages 面板对齐。
8. **体积与保留指标。** 导出 `agentflow.memory.checkpoint_bytes`、`messages_per_run`、`prompt_tokens_from_history`；超阈值告警。超大 JSON 没有指标时要到磁盘满才发现。
9. ~~**租户级保留 / 擦除。**~~ `POST /v1/runs/{id}/erase`、`POST /v1/organization/erase`、`POST /v1/retention/purge` + worker TTL sweeper；与 RBAC `tenant_id` 对齐；`MemoryErasureHook` 预留未来 Memory 行。

---

### 新增：真正的记忆服务（L1–L3）

建议拆成三期，每一期都有独立 API 与验收，避免「记忆服务」变成无边界项目。

#### M1 — Thread 短记忆（跨 Run 对话）

**目标：** 同一会话连续 `POST /v1/runs` 时，worker 能自动带上最近对话，而不是让客户端把历史塞进 `input`。

- 数据：`threads`（`id`, `tenant_id`, `project_id`, `agent_id`, 可选 `user_id`, `title`）+ `Run.thread_id`（nullable FK）。
- API：`POST /v1/threads`；`POST /v1/runs` 接受 `thread_id`；`GET /v1/threads/{id}/messages`（跨 Run 合并，按时间/index）。
- Runtime：`AdapterContext` 增加只读 `thread_messages: list[Message]`（已按窗口裁剪）。LangGraph / PydanticAI / AutoGen 从这里 seed，不各自查库。
- 控制台：按 thread 看连续对话；Run 详情显示所属 thread。
- **非目标：** 向量检索、自动抽事实。

**验收：** 两次 Run 共用 `thread_id`，第二次模型 prompt 含第一次的 user/assistant 回合；不同 `tenant_id` 的 thread 404；不传 `thread_id` 行为与今日一致。

#### M2 — Episodic 摘要 + Memory API

**目标：** Run 结束后异步生成情景摘要，供后续 Run 以「上次结论」形式注入，而不是把全文 transcript 永远塞进窗口。

- 数据：`memory_items`（`id`, `tenant_id`, `scope`∈{thread,agent,project,user}, `kind`∈{episode,fact,document_chunk,procedure}, `content`, `source_run_id`, `embedding`, `created_at`, `expires_at`, `metadata`）。
- 写入：worker 在 `run.succeeded` 后入队 `memory.ingest`；用小模型摘要 input/output/关键 tool 结果。失败 Run 可记 `kind=episode` 且标记 `outcome=failed`。
- 读取：`AdapterContext.memory.search(query, *, scope, limit)` → 命中列表（含 id、score、content、source）。默认把 top-k 以 `role=system` 或独立 `memory` 块注入，**必须**在 Step/Message `extra` 里留下 `memory_hit_ids` 以便审计。
- API：`GET /v1/memories?q=&scope=`、`POST /v1/memories`（人工写入）、`DELETE /v1/memories/{id}`（遗忘）。
- 内置工具：`memory.search` / `memory.store`（走 `AdapterToolSurface`，与 MCP 工具同一套 `ToolCall` 行）。Agent 按需召回，避免每次无脑注入。
- 向量：Postgres `pgvector`；embedding 模型可配。文档 RAG 作为 `kind=document_chunk` 的 ingest 管道，不另起一套 store。

**验收：** 新 Run 能召回「三天前该 thread 已批准方案 X」；控制台能看到注入了哪些 memory id；删除一条 fact 后下一次 search 不再命中；跨租户 search 为空。

#### M3 — Semantic 治理与 Procedural（可选）

- 事实冲突：同一 `key`（如 `user.preferred_language`）新写入覆盖旧值并留 `superseded_by`。
- 记忆评测：回归套件增加「是否错误召回过期事实 / 是否漏召回」用例，挂到现有 `regression-executions`。
- Procedural：把成功的 tool 序列收成 `kind=procedure`，仅对同 agent + 相似 input 检索；默认关闭。
- 多模态附件：与 Phase 5 流式附件共用对象存储，记忆层只存引用与 caption embedding。

---

### 数据模型草案（M1–M2）

相对 [data-model.md](data-model.md) 的增量，不改现有 `Message` 语义（它仍是 Run transcript）：

```
Thread ||--o{ Run : contains
Thread ||--o{ MemoryItem : scoped
Agent  ||--o{ MemoryItem : scoped
MemoryItem }o--o| Run : source

Thread { id PK, tenant_id, project_id, agent_id, user_id, title }
Run    { ... existing ..., thread_id FK nullable }
MemoryItem {
  id PK, tenant_id, project_id, agent_id, thread_id, user_id,
  kind, content, embedding vector, source_run_id,
  metadata, expires_at
}
```

`Checkpoint` 继续只服务 resume；禁止把长期事实写进 `Checkpoint.state`。

### Adapter 契约增量

```python
@dataclass
class AdapterContext:
    # 现有字段...
    thread_id: str | None = None
    memory: MemoryPortal | None = None  # search / store / list_window

class MemoryPortal:
    async def window(self) -> list[dict]  # L1 已裁剪
    async def search(self, query: str, *, limit: int = 8) -> list[MemoryHit]
    async def store(self, content: str, *, kind: str = "fact") -> str
```

Adapters **不得** import SQLAlchemy 查 `messages` / `memory_items`（与现有「只通过 `ctx.emit_*` 写状态」同一纪律）。官方 LangGraph / PydanticAI / AutoGen 只在 seed 时调用 `window()`；需要主动记忆的 agent 走 builtin `memory.*` 工具。

### 控制台

- Thread 列表与 thread 内 Run 时间线。
- Memory inspector：按 scope 浏览、搜索、手动 pin/forget。
- Run 详情：标注「本步注入的 memory hits」；Messages 支持折叠 system / prompt_echo。
- Checkpoint 面板：显示字节数；大 blob 默认折叠。

### 明确不做（除非单独立项）

- 把 LangGraph `PostgresSaver` 当产品记忆。
- 在 adapter 内直接调 OpenAI Assistants Threads。
- 无租户过滤的全局向量库。
- 用 Redis 当长期记忆（只适合 L1 热窗口缓存）。
- 在 v1 把 `Message.content` 改成多模态 JSON（等 Phase 5 附件方案）。

### 建议实施顺序

1. L0 优化 1–3（checkpoint 瘦身 + resume 不塞大 blob）——不改 API 契约，风险低。
2. L0 优化 4–6（窗口、分页、去重 emit）——开始动 API 与 LangGraph。
3. M1 Thread —— 第一个用户可感知的「记忆」。
4. M2 MemoryItem + pgvector + `memory.*` 工具 + 注入审计。
5. M3 治理与评测 —— 与回归套件一起。

---

## 建议下一步

1. ~~**SSE `Last-Event-ID` 重放**~~ — 已完成：`backend/app/events/bus.py`、`backend/app/api/v1/events.py`、Java `EventStreamService`
2. **队列 OTel 指标** — `backend/app/worker/monitor.py`、`backend/app/core/telemetry.py`
3. **Step 时间线 + ToolCall 面板** — `frontend/app/runs/`、`frontend/components/`
4. **人工审批 UI** — 基于 `waiting_human` + resume API，Phase 4 前可先做雏形
5. **Agent Memory L0 瘦身** — checkpoint 不再拷贝 messages；`_resume` 只带 index。见上方专项。

## 从哪里入手

| 目标 | 入口 |
| --- | --- |
| 事件重放 | `backend/app/events/bus.py`、`backend/app/api/v1/events.py` |
| 修控制台 | `frontend/app/runs/`、`frontend/components/` |
| 新 adapter | `backend/app/adapters/` + `__init__.py` 注册；MCP 见 [architecture.md](architecture.md#mcp-tool-bridge) |
| 扩展 API | 先改 [api-contract.md](api-contract.md)，再实现 Java API；涉及执行协议时同步 Python Worker |
| 队列可靠性 | `backend/app/worker/queue.py`、`backend/app/worker/monitor.py` |
| 可观测性 | `backend/app/core/telemetry.py`、Java `RedMetricsFilter` |
| Working memory 瘦身 | `backend/app/adapters/langgraph_adapter.py`（checkpoint 内容）、`backend/app/runtime/resume_context.py`、Python/Java `retry_run` |
| Thread / 长期记忆 | 先改 [data-model.md](data-model.md) + [api-contract.md](api-contract.md)；`AdapterContext` 增 `memory`；Java `RunsController` 接受 `thread_id`；控制台 `frontend/app/runs/[id]/page.tsx` |
