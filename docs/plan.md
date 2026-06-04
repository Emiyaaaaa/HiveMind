# AgentFlow 后续开发计划

架构与数据模型见 [architecture.md](architecture.md) 与 [data-model.md](data-model.md)。

**最后核对：** 2026-06-03

## 优化方向

按投入产出比排序：

1. **事件总线持久化。** Redis pub/sub 无订阅者时会丢消息；支持 `Last-Event-ID` 重放。
2. **队列 OTel 指标与背压。** 深度/消费者延迟已导出为 `agentflow.queue.*`；worker 利用率见 `agentflow.worker.utilization`；p95 面板见 `docker/grafana/dashboards/agentflow-observability.json`。
3. **控制台调试体验。** Step 可视化时间线、独立 ToolCall 检查面板。
4. **LangGraph adapter 扩展。** 更多 graph 模式、MCP 工具协议集成。
5. **双向流式传输。** WebSocket / WebTransport + SSE 降级，支持双向取消与审批。

## 可引入的先进技术

| 领域 | 候选方案 | 价值 |
| --- | --- | --- |
| 长任务编排 | Temporal、Restate | 超越 Redis ACK 的 durable timer、saga、人工审批 |
| LLM 可观测 | Langfuse、Arize Phoenix、OTel GenAI | 在现有 Step/Message 之上做 trace 与 eval |
| 工具协议 | MCP | 标准化 adapter 工具面 |
| 向量 / 记忆 | pgvector、LanceDB | Agent 记忆与 RAG，与 adapter 解耦 |
| 认证与多租户 | OIDC + `tenant_id` | RBAC、审计、团队隔离 |
| SDK 生成 | OpenAPI → TS/Python | Java、FastAPI、前端类型自动同步 |
| 部署 | Helm、HPA | 将 compose profile 产品化 |

## 路线图

### Phase 2 收尾 — 可观测性与运行控制（2026 Q2）

**目标：** 控制台调试闭环、事件可靠性与运行时指标。

- [ ] Step 时间线组件（节点延迟与状态流转）
- [ ] 独立 ToolCall 检查面板（参数/结果/错误结构化浏览）
- [ ] SSE 事件重放（`Last-Event-ID` / 持久化 event log）
- [x] 队列深度、worker 利用率导出为 OTel/Prometheus 指标
- [ ] p95 耗时仪表盘与告警

**验收：** 控制台展示可视化时间线；断连 SSE 可补全事件；队列指标可在 Grafana 查看。

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
- [ ] 细粒度流式：推理块、多模态附件（DB 持久化）

## 建议下一步

1. **SSE `Last-Event-ID` 重放** — `backend/app/events/bus.py`、`backend/app/api/v1/events.py`
2. **队列 OTel 指标** — `backend/app/worker/monitor.py`、`backend/app/core/telemetry.py`
3. **Step 时间线 + ToolCall 面板** — `frontend/app/runs/`、`frontend/components/`
4. **人工审批 UI** — 基于 `waiting_human` + resume API，Phase 4 前可先做雏形

## 从哪里入手

| 目标 | 入口 |
| --- | --- |
| 事件重放 | `backend/app/events/bus.py`、`backend/app/api/v1/events.py` |
| 修控制台 | `frontend/app/runs/`、`frontend/components/` |
| 新 adapter | `backend/app/adapters/` + `__init__.py` 注册 |
| 扩展 API | 先改 [api-contract.md](api-contract.md)，再同步 Java + Python |
| 队列可靠性 | `backend/app/worker/queue.py`、`backend/app/worker/monitor.py` |
| 可观测性 | `backend/app/core/telemetry.py`、Java `RedMetricsFilter` |
