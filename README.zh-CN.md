# AgentFlow

> 面向 multi-agent 系统的 Python-first 运行时层，提供持久化运行状态、
> 流式执行事件和可插拔的编排接口。

[English](README.md) · [架构](docs/architecture.md) · [数据模型](docs/data-model.md)

[![CI](https://github.com/your-org/agentflow/actions/workflows/ci.yml/badge.svg)](https://github.com/your-org/agentflow/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org)

AgentFlow 提供 multi-agent 应用所需的运行时基础设施。它不替代
LangGraph、AutoGen 或 CrewAI 这类编排框架，而是在它们外层提供统一的执行模型：
agent 以 run 的形式被调用，run 产生有序的 step 和 message，tool call 被持久化记录，
每一次状态变化都可以作为事件流推送给客户端。

这个项目适合从 agent 原型走向可观测服务的场景：你可以保留现有编排框架，
同时获得运行历史、事件流、调试视图和框架切换边界，而不需要为每个 agent
项目重复实现这些基础能力。

> 项目状态：早期 MVP。当前实现已经确定核心运行时形态，但公开 API 在稳定版前仍可能调整。

## 设计动机

多数 agent 框架主要关注本地编排：prompt、tool、graph、role 和 model call。
真正作为服务运行时，还需要处理框架外的一组工程问题：

- 进程重启后仍可查询的 run 历史；
- 用于调试和审计的 step、message、tool-call 有序记录；
- 面向前端和 SDK 的执行事件流；
- cancel、retry、resume 等运行控制能力；
- 可替换或混用不同编排框架的稳定抽象；
- 面向开发和运维的运行检查控制台。

AgentFlow 聚焦在这个运行时边界。核心服务保持明确且可读：FastAPI 负责 HTTP 与
SSE，SQLAlchemy 负责持久化，事件总线负责实时更新，adapter 接口负责接入不同编排框架。

## 核心能力

- **编排 adapter。** 默认 adapter 使用 LangGraph。AutoGen、CrewAI、
  PydanticAI 或内部框架可以通过相同接口注册接入，不需要修改 API 或数据库模型。
- **持久化执行模型。** `Run`、`Step`、`Message`、`ToolCall` 和 `Checkpoint`
  是一等数据库实体，为不同编排引擎提供统一的可观测数据面。
- **Server-Sent Events。** run 生命周期中的状态变化会被发布为 SSE 事件，
  客户端无需轮询即可跟踪执行过程。
- **轻量管理控制台。** Next.js 控制台支持 run 列表、run 详情、step 和 message
  展示，以及实时事件流订阅。
- **面向贡献者的技术栈。** Python 3.12、FastAPI、Pydantic v2、SQLAlchemy 2、
  Alembic、Redis、`uv`、Next.js 和 TypeScript。技术选择尽量使用社区常规方案。

## 架构

```
┌───────────────────┐  REST   ┌─────────────────────┐
│  Next.js 控制台   │ ──────▶ │   FastAPI 服务       │
│  (app/runs/...)   │ ◀─SSE── │  api/v1, services/   │
└───────────────────┘         └──────────┬──────────┘
                                         │
                                         ▼
                              ┌──────────────────────┐
                              │   编排 Adapter       │
                              │  (LangGraph、Echo...)│
                              └──────────┬──────────┘
                                         │ 事件
                                         ▼
                              ┌──────────────────────┐
                              │   Postgres + Redis   │
                              └──────────────────────┘
```

服务流程、adapter 契约和数据库模型见
[docs/architecture.md](docs/architecture.md) 与
[docs/data-model.md](docs/data-model.md)。

## 快速开始

依赖：Docker、[`uv`](https://github.com/astral-sh/uv) 和 Node.js 20+。

```bash
# 1. 启动依赖服务
docker compose up -d postgres redis

# 2. 启动后端
cd backend
cp .env.example .env
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000

# 3. 启动控制台
cd ../frontend
npm install
npm run dev
```

打开 http://localhost:3000。默认 `echo` adapter 在本地执行，不需要配置模型服务密钥。

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
├── backend/                FastAPI runtime + LangGraph adapter
│   ├── app/
│   │   ├── adapters/       编排 adapter
│   │   ├── api/v1/         HTTP 路由
│   │   ├── core/           配置与日志
│   │   ├── db/             SQLAlchemy session 与 base
│   │   ├── events/         内存版与 Redis 事件总线
│   │   ├── models/         ORM 模型
│   │   ├── schemas/        Pydantic schema
│   │   └── services/       run 生命周期服务
│   ├── alembic/            数据库迁移
│   └── tests/
├── frontend/               Next.js 管理控制台
├── docs/                   架构与数据模型
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

在 `app/adapters/__init__.py` 中注册 adapter。API、持久化模型、事件流和控制台
都会继续通过统一的运行时契约工作。

## Roadmap

- [x] **Phase 1：运行时核心。** agents、runs、steps、tool calls、
      checkpoints、SSE、LangGraph 与 Echo adapters、控制台 MVP。
- [ ] **Phase 2：可观测性。** step 时间线、retry 与 resume 操作、
      token 和成本汇总。
- [ ] **Phase 3：可扩展性。** 插件注册表、MCP tool adapter、
      官方 Python SDK 与 TypeScript SDK。
- [ ] **Phase 4：生产能力。** 基于 Temporal 的长任务、人工审批、
      RBAC、OpenTelemetry 导出和部署模板。

## 参与贡献

当前阶段比较有价值的贡献包括：

1. 运行快速开始流程，并反馈安装、启动或文档问题。
2. 为其他编排框架实现 adapter。
3. 改进控制台，例如执行指标、trace 视图或 tool-call 检查面板。
4. 补充 run 生命周期、事件流和 adapter 行为相关测试。

较大的改动建议先开 issue 或 discussion，便于在实现前确认设计方向。

## License

Apache 2.0。
