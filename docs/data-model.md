# Data model

AgentFlow stores every adapter execution in a small set of tables. The shape
is deliberately framework-agnostic so a single UI and SDK can render any
agent system.

## Entities

```mermaid
erDiagram
    Agent ||--o{ Run : has
    Run ||--o{ Step : has
    Run ||--o{ Message : has
    Run ||--o{ Checkpoint : has
    Step ||--o{ ToolCall : has
    Step }o--|| Message : "optional step_id"

    Agent {
        string id PK
        string name UK
        string adapter
        json config
    }
    Run {
        string id PK
        string agent_id FK
        string adapter
        string status
        json input
        json output
        text error
        json metadata
    }
    Step {
        string id PK
        string run_id FK
        int index
        string node
        string status
        json input
        json output
        text error
        int latency_ms
        int tokens_in
        int tokens_out
    }
    Message {
        string id PK
        string run_id FK
        string step_id FK
        int index
        string role
        string name
        text content
        string tool_call_id
        json extra
    }
    ToolCall {
        string id PK
        string step_id FK
        string name
        json arguments
        json result
        text error
        int latency_ms
    }
    Checkpoint {
        string id PK
        string run_id FK
        int index
        string label
        json state
    }
```

## Status state machine

```mermaid
stateDiagram-v2
    [*] --> pending
    pending --> running : start_run
    running --> succeeded : adapter returns success
    running --> failed : adapter raises / returns failed
    running --> cancelled : cancel_run
    running --> waiting_human : adapter pauses for approval
    waiting_human --> running : resume
    waiting_human --> cancelled : cancel_run
    succeeded --> [*]
    failed --> [*]
    cancelled --> [*]
```

## Design notes

- **IDs are ULIDs** (26-character strings). They are sortable by time, easy
  to log, and safer than auto-increment ids when the runtime fans out to
  multiple workers.
- **`metadata` is a JSON column** named `metadata_` in Python because
  `metadata` is reserved on `DeclarativeBase`. The column on disk is still
  `metadata`.
- **`Checkpoint.state` is opaque to the runtime.** Each adapter decides how
  to encode resumable state (LangGraph snapshot bytes encoded as JSON,
  AutoGen conversation, custom state machines).
- **`Step.index` is monotonic per run.** Use it for ordering instead of
  `created_at` so retries and replays stay stable.
- **`Message.step_id` is optional** so an adapter can attach a message to a
  specific node tick when it makes sense, while keeping the run-level
  ordering authoritative.

## Indexes

| Index | Purpose |
| --- | --- |
| `ix_runs_status` | filter pending / running runs from a worker |
| `ix_runs_agent_id` | list runs for an agent |
| `ix_steps_run_index` | render the step timeline in O(log n) |
| `ix_messages_run_index` | stream messages in order |
| `ix_tool_calls_step` | render tool calls inside a step |
| `ix_checkpoints_run_index` | replay from the latest checkpoint |
