# AgentFlow Python SDK

Typed client for the AgentFlow `/v1` HTTP API. The OpenAPI contract lives in
[`openapi/openapi.yaml`](../../openapi/openapi.yaml); regenerate REST stubs with
`scripts/gen/generate-sdks.sh` when the API changes.

## Install

```bash
cd sdk/python
pip install -e .
```

## Usage

```python
from agentflow_sdk import AgentFlowClient, subscribe_run_events

client = AgentFlowClient("http://localhost:8000", api_key="dev-admin")
run = client.create_run("01HZ...", input={"prompt": "hello"})
print(run.id, run.status)

for event in subscribe_run_events(
    "http://localhost:8000",
    run.id,
    api_key="dev-admin",
):
    print(event.type, event.data)
    if event.type.startswith("run."):
        break
```

`create_run` maps to `POST /v1/runs`. `subscribe_run_events` wraps the SSE
stream at `GET /v1/events/{run_id}` with optional `Last-Event-ID` replay.

### Human approval, retry and threads

```python
from agentflow_sdk import AgentFlowClient

client = AgentFlowClient("http://localhost:8000", api_key="dev-operator")

# Conversation: the worker seeds later runs with the thread's recent turns.
thread = client.create_thread("01HZ...", title="Support chat", user_id="user-42")
run = client.create_run("01HZ...", input={"prompt": "refund order 42"}, thread_id=thread.id)

# Stops on succeeded / failed / cancelled *or* waiting_human.
run = client.wait_for_run(run.id, timeout=120)
if run.status == "waiting_human":
    run = client.resume_run(run.id, input={"approval": "approved"})
    run = client.wait_for_run(run.id, timeout=120)
if run.status == "failed":
    run = client.retry_run(run.id)            # latest checkpoint; 409 unless failed

for message in client.iter_run_messages(run.id, page_size=50):   # follows next_cursor
    print(message["role"], message["content"])
for event in client.get_run_audit(run.id):                        # cancel / resume trail
    print(event.action, event.actor_subject, event.detail)
page = client.list_thread_messages(thread.id, limit=20)          # cross-run transcript
```

| Method | Endpoint |
| --- | --- |
| `create_run(agent_id, input=, metadata=, adapter=, thread_id=)` | `POST /v1/runs` |
| `get_run` / `cancel_run` | `GET` / `POST …/cancel` |
| `retry_run(run_id, checkpoint_index=)` | `POST /v1/runs/{id}/retry` |
| `resume_run(run_id, input=)` | `POST /v1/runs/{id}/resume` |
| `wait_for_run(run_id, timeout=, poll_interval=, until=)` | polls `GET /v1/runs/{id}`; raises `RunTimeoutError` (carries the last `Run`) |
| `list_run_messages` / `iter_run_messages` | `GET /v1/runs/{id}/messages?cursor=&limit=` |
| `get_run_audit` | `GET /v1/runs/{id}/audit` |
| `create_thread` / `get_thread` / `list_thread_runs` / `list_thread_messages` | `/v1/threads…` |

Server errors surface as `httpx.HTTPStatusError` (for example 409 when
retrying a run that is not `failed`).

## Tests

```bash
cd sdk/python && uv run --with pytest pytest -q
```
