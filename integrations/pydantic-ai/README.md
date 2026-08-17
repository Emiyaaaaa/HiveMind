# AgentFlow PydanticAI adapter

This optional plugin runs an existing PydanticAI `Agent` and translates its
text stream, usage, result, and native tool/MCP events to AgentFlow's shared
runtime contract.

## Install

Install the backend and plugin in every Python worker, then restart the worker
so entry-point discovery runs again:

```bash
pip install agentflow agentflow-pydantic-ai
```

From this repository:

```bash
pip install -e ./backend -e ./integrations/pydantic-ai
```

The package registers `pydantic-ai` in the `agentflow.adapters` entry-point
group. It does not add PydanticAI to AgentFlow's core dependencies.

## Define the Agent

Expose a zero-argument factory from code installed in the worker environment:

```python
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPToolset


def create_agent() -> Agent:
    knowledge = MCPToolset("knowledge_server.py")
    return Agent(
        "openai:gpt-4o-mini",
        instructions="Use the knowledge base when helpful.",
        toolsets=[knowledge],
    )
```

The factory owns the PydanticAI model, instructions, tools, MCP servers,
validators, and output type. Returning a fresh Agent per run avoids accidental
state sharing between runs.

Install the MCP client extra when the factory uses `MCPToolset`:

```bash
pip install "agentflow-pydantic-ai[mcp]"
```

## AgentFlow config

```json
{
  "adapter": "pydantic-ai",
  "config": {
    "agent_factory": "myapp.agents:create_agent"
  }
}
```

`agent_factory` imports and executes trusted Python code in the worker process.
Only administrators should be allowed to configure it; this plugin is not a
sandbox.

One PydanticAI run maps to one AgentFlow step. The plugin emits user and
assistant messages, token deltas, provider usage/cost when available, and
AgentFlow-owned ToolCall IDs for PydanticAI function-tool and MCP events.

The MVP deliberately does not rebuild Agents from JSON, route tools through
`AdapterToolSurface`, or implement checkpoint/retry, HITL, and deferred tools.
PydanticAI 2.27 or later in the 2.x series is supported.
