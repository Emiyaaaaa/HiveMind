# AgentFlow

> 面向 multi-agent 系统的 Python-first 运行时层，提供持久化运行状态、
> 流式执行事件和可插拔的编排接口。

[English](README.md) · [架构](docs/architecture.md) · [数据模型](docs/data-model.md) · [后续开发计划](docs/plan.md)

[License](LICENSE)
[Python](https://www.python.org)

AgentFlow 提供 multi-agent 应用所需的运行时基础设施。它不替代
LangGraph、AutoGen 或 CrewAI 这类编排框架，而是在它们外层提供统一的执行模型：
agent 以 run 的形式被调用，run 产生有序的 step 和 message，tool call 被持久化记录，
每一次状态变化都可以作为事件流推送给客户端。

这个项目适合从 agent 原型走向可观测服务的场景：你可以保留现有编排框架，
同时获得运行历史、事件流、调试视图和框架切换边界，而不需要为每个 agent
项目重复实现这些基础能力。

## 设计动机

多数 agent 框架主要关注本地编排：prompt、tool、graph、role 和 model call。
真正作为服务运行时，还需要处理框架外的一组工程问题：

- 进程重启后仍可查询的 run 历史；
- 用于调试和审计的 step、message、tool-call 有序记录；
- 面向前端和 SDK 的执行事件流；
- cancel、retry、resume 等运行控制能力；
- 可替换或混用不同编排框架的稳定抽象；
- 面向开发和运维的运行检查控制台。

AgentFlow 聚焦在这个运行时边界：Java/Spring Boot 提供 HTTP 与 SSE，
Python worker 执行 adapter，SQLAlchemy + Alembic 负责持久化，Redis 负责
任务队列与实时事件。

## 核心能力

- **编排 adapter。** 默认 adapter 使用 LangGraph。AutoGen、CrewAI、
PydanticAI 或内部框架可以通过相同接口注册接入，不需要修改 API 或数据库模型。
- **持久化执行模型。** `Run`、`Step`、`Message`、`ToolCall` 和 `Checkpoint`
是一等数据库实体，为不同编排引擎提供统一的可观测数据面。
- **Server-Sent Events。** run 生命周期中的状态变化会被发布为 SSE 事件，
客户端无需轮询即可跟踪执行过程。
- **轻量管理控制台。** Next.js 控制台支持 run 列表、run 详情、step 和 message
展示，以及实时事件流订阅。
- **面向贡献者的技术栈。** Java 21、Spring Boot 3、Python 3.12、
SQLAlchemy 2、Alembic、Redis、`uv`、Next.js 和 TypeScript。

## 架构

前端对接 Java/Spring Boot API（[`backend-java/`](backend-java/)）。
Agent 编排在 Python worker（[`backend/`](backend/)）中执行，通过 Redis
队列与事件总线与 API 协作。

```
┌───────────────────┐  REST   ┌──────────────────────┐
│  Next.js 控制台   │ ──────▶ │  Java/Spring Boot API│
│  (app/runs/...)   │ ◀─SSE── │  /v1/* + SSE 桥接    │
└───────────────────┘         └──────────┬───────────┘
                                         │ jobs / cancel / events (Redis)
                                         ▼
                              ┌──────────────────────┐
                              │ Python worker (uv)   │
                              │  app.worker.runner   │
                              └──────────┬───────────┘
                                         ▼
                              ┌──────────────────────┐
                              │ 编排 Adapter         │
                              │ (LangGraph、Echo...) │
                              └──────────┬───────────┘
                                         ▼
                              ┌──────────────────────┐
                              │  Postgres（状态）    │
                              └──────────────────────┘
```

详见 [docs/architecture.md](docs/architecture.md)、
[docs/deployment.md](docs/deployment.md)、
[docs/api-contract.md](docs/api-contract.md) 与
[docs/data-model.md](docs/data-model.md)。

## 快速开始

依赖：Docker、[`uv`](https://github.com/astral-sh/uv)、Node.js 20+、JDK 21 与 Maven 3.9+。

```bash
docker compose up -d postgres redis
cd backend && uv sync && uv run alembic upgrade head
AGENTFLOW_WORKER_MODE=queue uv run python -m app.worker   # 单独终端
cd ../backend-java && mvn spring-boot:run                   # 单独终端
cd ../frontend && npm install && npm run dev                # 单独终端
```

或使用 Docker Compose：

```bash
cd backend && uv sync && uv run alembic upgrade head
docker compose --profile app up --build
```

打开 [http://localhost:3000](http://localhost:3000)。默认 `echo` adapter 在本地执行，不需要配置模型服务密钥。

## 通过 API 创建 run

创建 agent：

```bash
curl -X POST http://localhost:8000/v1/agents \
  -H "content-type: application/json" \
  -d '{
        "name": "writer",
        "adapter": "langgraph",
        "config": {
          "model": "openai/gpt-4o-mini",
          "system_prompt": "你是一位简洁的技术写作者。"
        }
      }'
```

启动 run：

```bash
curl -X POST http://localhost:8000/v1/runs \
  -H "content-type: application/json" \
  -d '{"agent_id": "<上一步返回的 id>", "input": {"prompt": "用两句话解释 SSE。"}}'
```

订阅该 run 的事件流：

```bash
curl -N http://localhost:8000/v1/events/<run_id>
```

## 目录结构

```
agentflow/
├── backend/                Python 运行时：adapter、worker、Alembic schema
│   ├── app/
│   │   ├── adapters/       编排 adapter
│   │   ├── core/           配置与日志
│   │   ├── db/             SQLAlchemy session 与 base
│   │   ├── events/         内存版与 Redis 事件总线
│   │   ├── models/         ORM 模型
│   │   ├── schemas/        Pydantic schema
│   │   └── worker/         队列、取消信号、worker 循环
│   ├── alembic/            数据库 schema
│   └── tests/
├── backend-java/           Spring Boot API 服务
├── frontend/               Next.js 管理控制台
├── docs/                   架构、部署、API 契约
└── docker-compose.yml
```

## Adapter 接口

adapter 只需要实现一个异步方法。运行时会传入 `AdapterContext`；
adapter 通过 context 发出生命周期事件，并在执行进入终态时返回 `AdapterResult`。

```python
from app.adapters.base import AdapterContext, AdapterResult, OrchestratorAdapter
from app.models.run import RunStatus

class MyAdapter(OrchestratorAdapter):
    async def run(self, ctx: AdapterContext) -> AdapterResult:
        await ctx.emit_step_started(index=0, node="think")
        await ctx.emit_message(role="assistant", content="hello")
        await ctx.emit_step_completed(index=0, node="think")
        return AdapterResult(status=RunStatus.SUCCEEDED, output={"ok": True})
```

在 `app/adapters/__init__.py` 中注册 adapter。Worker 会自动加载；
API、持久化模型、事件流和控制台继续通过统一的运行时契约工作。

## 当前架构（摘要）

AgentFlow 是**分层运行时**：Java API 层、Python 执行层、共享基础设施。


| 层级     | 技术栈                          | 职责                                   |
| -------- | ---------------------------- | ------------------------------------ |
| 控制台    | Next.js 15、React Query、SSE   | Agent/Run 管理、实时事件流                   |
| API      | Java 21、Spring Boot 3、JPA    | REST `/v1/*`、SSE 桥接、入队、取消            |
| Worker   | Python asyncio、`RunExecutor` | 消费 Redis 任务、执行 adapter、写 Postgres    |
| Adapter  | LangGraph、Echo（可注册）          | 统一接口下的框架编排                           |
| 状态     | Postgres 16、Alembic          | Run、Step、Message、ToolCall、Checkpoint |
| 消息     | Redis Streams + pub/sub      | 至少一次任务队列、取消信号、实时事件                   |


**数据流：** `POST /v1/runs` → API 写入 `pending` → Redis 任务 → worker 执行  
adapter → 持久化 + 事件 → SSE 推送到控制台。Postgres 是唯一真相源；Redis 仅做协调。

详见 [docs/deployment.md](docs/deployment.md)。

## License

Apache 2.0。
