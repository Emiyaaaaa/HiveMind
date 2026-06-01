# AgentFlow 后续开发计划

优化方向、可引入的先进技术，以及分阶段路线图。架构与数据模型见
[architecture.md](architecture.md) 与 [data-model.md](data-model.md)。

## 优化方向

按投入产出比排序：

1. **前端用事件驱动替代轮询。** Run 列表每 3s、详情页每 2s 轮询；改为 SSE/WebSocket
   推送状态变更。
2. **Worker 并发与背压。** 当前单 job 串行；增加可配置并行度、队列深度指标与消费者延迟告警。
3. **增强 LangGraph adapter。** 支持多节点 graph、工具注册、token/延迟写入 Step、流式 token 事件。
4. **实现 retry / resume。** 数据模型已有 Checkpoint 与 `waiting_human`，补齐 HTTP 动作与 adapter 钩子。
5. **事件总线持久化。** Redis pub/sub 无订阅者时会丢消息；支持 `Last-Event-ID` 重放。
6. **可观测性基线。** 在 API → worker → adapter 链路上接入 OpenTelemetry，导出 RED 指标。
7. **控制台体验。** Step 时间线、ToolCall 检查面板、token/成本汇总、Checkpoint 标记。

## 可引入的先进技术

| 领域 | 候选方案 | 价值 |
| --- | --- | --- |
| 长任务编排 | Temporal、Restate | 超越 Redis ACK 的 durable timer、saga、人工审批 |
| LLM 可观测 | Langfuse、Arize Phoenix、OTel GenAI | 在现有 Step/Message 之上做 trace 与 eval |
| 工具协议 | MCP | 标准化 adapter 工具面 |
| 流式传输 | WebTransport / WebSocket + SSE 降级 | 双向取消、审批、token 流 |
| 向量 / 记忆 | pgvector、LanceDB | Agent 记忆与 RAG，与 adapter 解耦 |
| 认证与多租户 | OIDC + `tenant_id` | RBAC、审计、团队隔离 |
| SDK 生成 | OpenAPI → TS/Python | Java、FastAPI、前端类型自动同步 |
| 部署 | Helm、HPA | 将 compose profile 产品化 |

## 路线图

### Phase 1 — 运行时核心 ✅（已完成）

- [x] 统一数据模型与 Adapter 接口
- [x] Echo / LangGraph adapter、SSE、Next.js 控制台 MVP
- [x] Redis Streams 任务队列（含 DLQ）与取消协议
- [x] Java/Spring Boot API 与独立 Python worker

### Phase 2 — 可观测性与运行控制（2026 Q2）

**目标：** 在控制台内完成调试、重试与成本核算。

- [ ] Step 时间线组件（节点延迟与状态）
- [ ] Adapter 写入 token/成本；Run 级汇总
- [ ] `POST /v1/runs/{id}/retry` 与 `POST /v1/runs/{id}/resume`
- [ ] SSE 事件重放（`Last-Event-ID`）
- [x] OpenTelemetry 全链路 trace（API → worker → adapter，RED 指标 + trace 传播）
- [ ] 队列深度、worker 利用率、p95 耗时等指标
- [x] Compose 集成测试与 CI（`integration` job）

**验收：** 失败 Run 可从 checkpoint 重试；控制台展示成本与时间线；Jaeger/Tempo 可见 trace。

### Phase 3 — 可扩展性与 SDK（2026 Q3）

**目标：** 第三方框架与工具可插拔，无需 fork runtime。

- [ ] Adapter 插件注册表（entry points / 动态加载）
- [ ] 官方 adapter：AutoGen、CrewAI、PydanticAI（按需求选 2 个）
- [ ] MCP tool adapter
- [ ] OpenAPI 规范 + Python/TypeScript SDK 自动生成
- [ ] Webhook 出站事件（`run.completed` 等）
- [ ] Agent 版本管理与配置 diff

**验收：** 新 adapter 以包形式发布；SDK 覆盖 create-run + subscribe-events；MCP 调用写入 ToolCall。

### Phase 4 — 生产与企业能力（2026 Q4）

**目标：** 多租户安全部署、治理与长任务。

- [ ] OIDC 认证与服务账号 API Key
- [ ] RBAC：组织/项目/Agent 作用域；cancel/resume 审计
- [ ] 人工审批 UI（`waiting_human` + 通知）
- [ ] Temporal（或 Restate）集成超长 Run
- [ ] Helm + Terraform；按队列延迟自动扩缩 worker
- [ ] Agent 级 token/成本配额

**验收：** 双租户演示；审批门控生效；24h+ 工作流在 worker 重启后仍可恢复。

### Phase 5 — 智能层（2027）

**目标：** 在 runtime 之上提供 eval、记忆与路由，而非塞进 adapter。

- [ ] Run 对比与回归套件
- [ ] Agent 记忆服务（对话 + 文档存储）
- [ ] 模型路由 / fallback 策略
- [ ] 定时与批量 Run
- [ ] 细粒度流式：token delta、推理块、多模态附件

## 从哪里入手

| 目标 | 入口 |
| --- | --- |
| 修控制台 | `frontend/app/runs/` |
| 新 adapter | `backend/app/adapters/` + `__init__.py` 注册 |
| 扩展 API | 先改 [api-contract.md](api-contract.md)，再同步 Java + Python |
| 队列可靠性 | `backend/app/worker/queue.py`、`backend-java/.../jobs/` |
| 可观测性 | OpenTelemetry 中间件（双 API + worker） |
