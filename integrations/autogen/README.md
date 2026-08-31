# AgentFlow AutoGen adapter

This optional plugin runs an existing AutoGen AgentChat agent or team and
translates its stream, usage, and tool events to AgentFlow's shared runtime
contract.

## Install

Install the backend and plugin in every Python worker, then restart the worker
so entry-point discovery runs again:

```bash
pip install agentflow agentflow-autogen
```

From this repository:

```bash
pip install -e ./backend -e ./integrations/autogen
```

The package registers `autogen` in the `agentflow.adapters` entry-point group.
It does not add AutoGen to AgentFlow's core dependencies.

## Define the agent or team

Expose a zero-argument factory from code installed in the worker environment:

```python
from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import OpenAIChatCompletionClient


def create_agent(*, agentflow_tools=None) -> AssistantAgent:
  tools = list(agentflow_tools or [])
  return AssistantAgent(
      name="assistant",
      model_client=OpenAIChatCompletionClient(model="gpt-4o-mini"),
      tools=tools,
      model_client_stream=True,
  )
```

For multi-agent runs, return a team with `run_stream()`:

```python
from autogen_agentchat.teams import RoundRobinGroupChat


def create_team() -> RoundRobinGroupChat:
  writer = create_agent()
  editor = create_agent()
  return RoundRobinGroupChat([writer, editor], max_turns=4)
```

The factory owns the AutoGen model client, instructions, native tools, and team
topology. Returning a fresh agent or team per run avoids accidental state
sharing between runs.

## AgentFlow config

Single agent:

```json
{
  "adapter": "autogen",
  "config": {
    "agent_factory": "myapp.agents:create_agent",
    "stream_tokens": true,
    "tools": ["echo"]
  }
}
```

Team:

```json
{
  "adapter": "autogen",
  "config": {
    "team_factory": "myapp.agents:create_team",
    "per_turn_steps": true
  }
}
```

`tools`, `mcp_servers`, and `mcp_auto_register` use the same format as other
AgentFlow adapters. When configured, the adapter exposes resolved tools to
AutoGen for the current run and delegates their execution back to
`AdapterToolSurface`. Factories may accept an optional `agentflow_tools`
keyword to merge bridged tools explicitly.

`agent_factory` / `team_factory` import and execute trusted Python code in the
worker process. Only administrators should be allowed to configure them; this
plugin is not a sandbox.

One single-agent run maps to one AgentFlow step. Team runs can emit one step per
agent turn when `per_turn_steps` is enabled (default for teams). The plugin
emits user and assistant messages, token deltas, provider usage when available,
and AgentFlow-owned ToolCall IDs for native AutoGen tool events.

The plugin deliberately does not rebuild agents from JSON or implement
checkpoint/retry or human-in-the-loop. AutoGen AgentChat 0.4.x is supported.
