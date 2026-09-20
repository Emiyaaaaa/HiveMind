import type {
  Agent,
  AgentQuotaStatus,
  AgentVersion,
  Message,
  RegressionExecution,
  RegressionExecutionResults,
  Run,
  RunAuditEvent,
  Step,
  Thread,
  ThreadMessage,
} from "@/lib/types";

const TENANT = "ten_demo";

function iso(hoursAgo: number, minuteOffset = 0): string {
  return new Date(
    Date.now() - hoursAgo * 3_600_000 - minuteOffset * 60_000,
  ).toISOString();
}

function emptyUsage() {
  return {
    tokens_in: 0,
    tokens_out: 0,
    cost_usd: 0,
    latency_ms: null as number | null,
    step_count: 0,
    failed_step_count: 0,
    tool_call_count: 0,
    failed_tool_call_count: 0,
  };
}

function usageFromSteps(steps: Step[]) {
  let tokens_in = 0;
  let tokens_out = 0;
  let cost_usd = 0;
  let latency_ms = 0;
  let hasLatency = false;
  let failed_step_count = 0;
  let tool_call_count = 0;
  let failed_tool_call_count = 0;
  for (const step of steps) {
    tokens_in += step.tokens_in ?? 0;
    tokens_out += step.tokens_out ?? 0;
    cost_usd += step.cost_usd ?? 0;
    if (step.latency_ms != null) {
      latency_ms += step.latency_ms;
      hasLatency = true;
    }
    if (step.status === "failed") failed_step_count += 1;
    for (const call of step.tool_calls ?? []) {
      tool_call_count += 1;
      if (call.error) failed_tool_call_count += 1;
    }
  }
  return {
    tokens_in,
    tokens_out,
    cost_usd,
    latency_ms: hasLatency ? latency_ms : null,
    step_count: steps.length,
    failed_step_count,
    tool_call_count,
    failed_tool_call_count,
  };
}

export const SEED_AGENT_IDS = {
  support: "agt_support_01",
  research: "agt_research_01",
  echo: "agt_echo_01",
  review: "agt_review_01",
} as const;

export const SEED_THREAD_IDS = {
  refund: "thr_refund_8841",
  research: "thr_research_2201",
} as const;

export const SEED_RUN_IDS = {
  succeededSupport: "run_ok_support_1001",
  waitingApproval: "run_wait_refund_1002",
  failedResearch: "run_fail_research_1003",
  runningLive: "run_live_review_1004",
  cancelled: "run_cancel_echo_1005",
  succeededBaseline: "run_ok_baseline_1006",
  succeededCandidate: "run_ok_candidate_1007",
} as const;

export function buildSeedAgents(): Agent[] {
  return [
    {
      id: SEED_AGENT_IDS.support,
      tenant_id: TENANT,
      name: "customer-support",
      description:
        "Handles refunds, order status, and escalation with tool use.",
      adapter: "langchain",
      config: {
        model: "gpt-4o-mini",
        temperature: 0.2,
        tools: ["lookup_order", "create_refund", "notify_slack"],
        system_prompt:
          "You are a helpful customer support agent for Acme Commerce.",
      },
      version: 3,
      created_at: iso(72),
      updated_at: iso(6),
    },
    {
      id: SEED_AGENT_IDS.research,
      tenant_id: TENANT,
      name: "research-assistant",
      description: "Multi-step web research with citations and checkpoints.",
      adapter: "langgraph",
      config: {
        model: "claude-sonnet-4",
        max_steps: 8,
        tools: ["web_search", "fetch_url", "summarize"],
      },
      version: 2,
      created_at: iso(48),
      updated_at: iso(12),
    },
    {
      id: SEED_AGENT_IDS.echo,
      tenant_id: TENANT,
      name: "echo-bot",
      description: "Deterministic echo adapter for smoke tests.",
      adapter: "echo",
      config: {},
      version: 1,
      created_at: iso(96),
      updated_at: iso(96),
    },
    {
      id: SEED_AGENT_IDS.review,
      tenant_id: TENANT,
      name: "code-reviewer",
      description: "Reviews pull requests and suggests fixes.",
      adapter: "openai_agents",
      config: {
        model: "gpt-4.1",
        tools: ["read_file", "run_linter"],
      },
      version: 4,
      created_at: iso(36),
      updated_at: iso(2),
    },
  ];
}

export function buildSeedQuotas(): Record<string, AgentQuotaStatus> {
  return {
    [SEED_AGENT_IDS.support]: {
      agent_id: SEED_AGENT_IDS.support,
      active: true,
      enforce: true,
      period: "month",
      period_key: "2026-09",
      period_start: "2026-09-01T00:00:00.000Z",
      period_end: "2026-10-01T00:00:00.000Z",
      max_tokens: 2_000_000,
      max_cost_usd: 50,
      used_tokens: 428_450,
      used_tokens_in: 210_200,
      used_tokens_out: 218_250,
      used_cost_usd: 12.84,
      run_count: 186,
      remaining_tokens: 1_571_550,
      remaining_cost_usd: 37.16,
      exceeded: false,
    },
    [SEED_AGENT_IDS.research]: {
      agent_id: SEED_AGENT_IDS.research,
      active: true,
      enforce: true,
      period: "week",
      period_key: "2026-W38",
      period_start: "2026-09-15T00:00:00.000Z",
      period_end: "2026-09-22T00:00:00.000Z",
      max_tokens: 500_000,
      max_cost_usd: 25,
      used_tokens: 412_880,
      used_tokens_in: 198_100,
      used_tokens_out: 214_780,
      used_cost_usd: 19.42,
      run_count: 47,
      remaining_tokens: 87_120,
      remaining_cost_usd: 5.58,
      exceeded: false,
    },
    [SEED_AGENT_IDS.echo]: {
      agent_id: SEED_AGENT_IDS.echo,
      active: false,
      enforce: false,
      period: null,
      period_key: null,
      period_start: null,
      period_end: null,
      max_tokens: null,
      max_cost_usd: null,
      used_tokens: 1_240,
      used_tokens_in: 620,
      used_tokens_out: 620,
      used_cost_usd: 0,
      run_count: 62,
      remaining_tokens: null,
      remaining_cost_usd: null,
      exceeded: false,
    },
    [SEED_AGENT_IDS.review]: {
      agent_id: SEED_AGENT_IDS.review,
      active: true,
      enforce: true,
      period: "day",
      period_key: "2026-09-19",
      period_start: "2026-09-19T00:00:00.000Z",
      period_end: "2026-09-20T00:00:00.000Z",
      max_tokens: 100_000,
      max_cost_usd: 8,
      used_tokens: 98_200,
      used_tokens_in: 52_100,
      used_tokens_out: 46_100,
      used_cost_usd: 7.65,
      run_count: 14,
      remaining_tokens: 1_800,
      remaining_cost_usd: 0.35,
      exceeded: false,
    },
  };
}

export function buildSeedVersions(): Record<string, AgentVersion[]> {
  return {
    [SEED_AGENT_IDS.support]: [
      {
        id: "ver_support_1",
        agent_id: SEED_AGENT_IDS.support,
        version: 1,
        description: "Initial support agent",
        adapter: "langchain",
        config: { model: "gpt-4o-mini", temperature: 0.4 },
        note: "bootstrap",
        created_at: iso(72),
      },
      {
        id: "ver_support_2",
        agent_id: SEED_AGENT_IDS.support,
        version: 2,
        description: "Added refund tool",
        adapter: "langchain",
        config: {
          model: "gpt-4o-mini",
          temperature: 0.3,
          tools: ["lookup_order", "create_refund"],
        },
        note: "refunds",
        created_at: iso(40),
      },
      {
        id: "ver_support_3",
        agent_id: SEED_AGENT_IDS.support,
        version: 3,
        description:
          "Handles refunds, order status, and escalation with tool use.",
        adapter: "langchain",
        config: {
          model: "gpt-4o-mini",
          temperature: 0.2,
          tools: ["lookup_order", "create_refund", "notify_slack"],
          system_prompt:
            "You are a helpful customer support agent for Acme Commerce.",
        },
        note: "slack escalate",
        created_at: iso(6),
      },
    ],
    [SEED_AGENT_IDS.research]: [
      {
        id: "ver_research_1",
        agent_id: SEED_AGENT_IDS.research,
        version: 1,
        description: "Basic research graph",
        adapter: "langgraph",
        config: { model: "claude-sonnet-4", max_steps: 4 },
        note: null,
        created_at: iso(48),
      },
      {
        id: "ver_research_2",
        agent_id: SEED_AGENT_IDS.research,
        version: 2,
        description: "Multi-step web research with citations and checkpoints.",
        adapter: "langgraph",
        config: {
          model: "claude-sonnet-4",
          max_steps: 8,
          tools: ["web_search", "fetch_url", "summarize"],
        },
        note: "more steps",
        created_at: iso(12),
      },
    ],
    [SEED_AGENT_IDS.echo]: [
      {
        id: "ver_echo_1",
        agent_id: SEED_AGENT_IDS.echo,
        version: 1,
        description: "Deterministic echo adapter for smoke tests.",
        adapter: "echo",
        config: {},
        note: null,
        created_at: iso(96),
      },
    ],
    [SEED_AGENT_IDS.review]: [
      {
        id: "ver_review_4",
        agent_id: SEED_AGENT_IDS.review,
        version: 4,
        description: "Reviews pull requests and suggests fixes.",
        adapter: "openai_agents",
        config: {
          model: "gpt-4.1",
          tools: ["read_file", "run_linter"],
        },
        note: "linter tool",
        created_at: iso(2),
      },
    ],
  };
}

export function buildSeedThreads(): Thread[] {
  return [
    {
      id: SEED_THREAD_IDS.refund,
      tenant_id: TENANT,
      project_id: "proj_acme_support",
      agent_id: SEED_AGENT_IDS.support,
      user_id: "user_maria_chen",
      title: "Refund for order #AC-94821",
      created_at: iso(8),
      updated_at: iso(1, 20),
    },
    {
      id: SEED_THREAD_IDS.research,
      tenant_id: TENANT,
      project_id: "proj_market_intel",
      agent_id: SEED_AGENT_IDS.research,
      user_id: "user_alex_nguyen",
      title: "Q3 vector DB landscape",
      created_at: iso(14),
      updated_at: iso(5),
    },
  ];
}

function supportSucceededSteps(): Step[] {
  const t0 = iso(3, 10);
  const t1 = iso(3, 9);
  const t2 = iso(3, 8);
  return [
    {
      id: "stp_ok_0",
      index: 0,
      node: "planner",
      status: "succeeded",
      input: { prompt: "Where is my order AC-94821?" },
      output: { plan: ["lookup_order", "reply"] },
      error: null,
      latency_ms: 420,
      tokens_in: 180,
      tokens_out: 64,
      cost_usd: 0.0012,
      tool_calls: [],
      created_at: t0,
      updated_at: t0,
    },
    {
      id: "stp_ok_1",
      index: 1,
      node: "tools",
      status: "succeeded",
      input: { tool: "lookup_order" },
      output: { status: "shipped", eta: "2026-09-20" },
      error: null,
      latency_ms: 890,
      tokens_in: 96,
      tokens_out: 40,
      cost_usd: 0.0008,
      tool_calls: [
        {
          id: "tc_lookup_1",
          name: "lookup_order",
          arguments: { order_id: "AC-94821" },
          result: {
            order_id: "AC-94821",
            status: "shipped",
            carrier: "UPS",
            tracking: "1Z999AA10123456784",
            eta: "2026-09-20",
          },
          error: null,
          latency_ms: 640,
        },
      ],
      created_at: t1,
      updated_at: t1,
    },
    {
      id: "stp_ok_2",
      index: 2,
      node: "responder",
      status: "succeeded",
      input: {},
      output: {
        reply:
          "Your order AC-94821 shipped via UPS (1Z999AA10123456784) and is due Sep 20.",
      },
      error: null,
      latency_ms: 1100,
      tokens_in: 420,
      tokens_out: 88,
      cost_usd: 0.0021,
      tool_calls: [],
      created_at: t2,
      updated_at: t2,
    },
  ];
}

function supportSucceededMessages(): Message[] {
  return [
    {
      id: "msg_ok_0",
      index: 0,
      step_id: null,
      role: "user",
      name: null,
      content: "Where is my order AC-94821?",
      tool_call_id: null,
      extra: {},
      created_at: iso(3, 10),
    },
    {
      id: "msg_ok_1",
      index: 1,
      step_id: "stp_ok_1",
      role: "assistant",
      name: null,
      content: "Let me look up order AC-94821 for you.",
      tool_call_id: null,
      extra: {},
      created_at: iso(3, 9),
    },
    {
      id: "msg_ok_2",
      index: 2,
      step_id: "stp_ok_1",
      role: "tool",
      name: "lookup_order",
      content:
        '{"order_id":"AC-94821","status":"shipped","carrier":"UPS","tracking":"1Z999AA10123456784","eta":"2026-09-20"}',
      tool_call_id: "tc_lookup_1",
      extra: {},
      created_at: iso(3, 8),
    },
    {
      id: "msg_ok_3",
      index: 3,
      step_id: "stp_ok_2",
      role: "assistant",
      name: null,
      content:
        "Your order AC-94821 shipped via UPS (1Z999AA10123456784) and is due Sep 20. Want me to email the tracking link?",
      tool_call_id: null,
      extra: {},
      created_at: iso(3, 7),
    },
  ];
}

// Fix typo in iso call - iso(3, 8,) has trailing comma which is fine in JS
// Actually I wrote iso(3, 8, ) - that's fine

function waitingApprovalRun(): Run {
  const steps: Step[] = [
    {
      id: "stp_wait_0",
      index: 0,
      node: "intake",
      status: "succeeded",
      input: { prompt: "I want a full refund for order AC-94821" },
      output: { intent: "refund" },
      error: null,
      latency_ms: 510,
      tokens_in: 140,
      tokens_out: 32,
      cost_usd: 0.0009,
      tool_calls: [],
      created_at: iso(1, 40),
      updated_at: iso(1, 40),
    },
    {
      id: "stp_wait_1",
      index: 1,
      node: "policy_check",
      status: "succeeded",
      input: { order_total_usd: 189.0, reason: "changed_mind" },
      output: { requires_approval: true, refund_amount_usd: 189.0 },
      error: null,
      latency_ms: 220,
      tokens_in: 80,
      tokens_out: 24,
      cost_usd: 0.0004,
      tool_calls: [],
      created_at: iso(1, 38),
      updated_at: iso(1, 38),
    },
    {
      id: "stp_wait_2",
      index: 2,
      node: "human_approval",
      status: "waiting_human",
      input: { amount_usd: 189.0 },
      output: null,
      error: null,
      latency_ms: null,
      tokens_in: null,
      tokens_out: null,
      cost_usd: null,
      tool_calls: [],
      created_at: iso(1, 35),
      updated_at: iso(1, 35),
    },
  ];
  const messages: Message[] = [
    {
      id: "msg_wait_0",
      index: 0,
      step_id: null,
      role: "user",
      name: null,
      content: "I want a full refund for order AC-94821 — I changed my mind.",
      tool_call_id: null,
      extra: {},
      created_at: iso(1, 40),
    },
    {
      id: "msg_wait_1",
      index: 1,
      step_id: "stp_wait_1",
      role: "assistant",
      name: null,
      content:
        "Order AC-94821 totals $189.00. Policy requires manager approval for full refunds over $100 when the reason is change-of-mind. Draft: approve a $189.00 refund to the original card.",
      tool_call_id: null,
      extra: {},
      created_at: iso(1, 36),
    },
  ];
  return {
    id: SEED_RUN_IDS.waitingApproval,
    tenant_id: TENANT,
    agent_id: SEED_AGENT_IDS.support,
    thread_id: SEED_THREAD_IDS.refund,
    adapter: "langchain",
    status: "waiting_human",
    input: { prompt: "I want a full refund for order AC-94821" },
    output: {
      awaiting: "Approve $189.00 refund to original payment method?",
      node: "human_approval",
      reply:
        "Draft: approve a $189.00 refund to the original card for order AC-94821.",
      refund_amount_usd: 189.0,
    },
    error: null,
    created_at: iso(1, 40),
    updated_at: iso(1, 20),
    steps,
    messages,
    messages_truncated: false,
    checkpoints: [
      {
        id: "cp_wait_0",
        index: 0,
        label: "after_policy_check",
        created_at: iso(1, 37),
      },
    ],
    usage: usageFromSteps(steps),
  };
}

function failedResearchRun(): Run {
  const steps: Step[] = [
    {
      id: "stp_fail_0",
      index: 0,
      node: "search",
      status: "succeeded",
      input: { query: "vector database comparison 2026" },
      output: { hits: 12 },
      error: null,
      latency_ms: 2100,
      tokens_in: 220,
      tokens_out: 90,
      cost_usd: 0.0045,
      tool_calls: [
        {
          id: "tc_search_1",
          name: "web_search",
          arguments: { query: "vector database comparison 2026", top_k: 8 },
          result: {
            hits: [
              { title: "Pinecone vs Weaviate", url: "https://example.com/a" },
              { title: "Qdrant benchmarks", url: "https://example.com/b" },
            ],
          },
          error: null,
          latency_ms: 1800,
        },
      ],
      created_at: iso(5, 30),
      updated_at: iso(5, 28),
    },
    {
      id: "stp_fail_1",
      index: 1,
      node: "fetch",
      status: "failed",
      input: { url: "https://example.com/a" },
      output: null,
      error: "fetch_url timed out after 15000ms",
      latency_ms: 15020,
      tokens_in: 40,
      tokens_out: 12,
      cost_usd: 0.0003,
      tool_calls: [
        {
          id: "tc_fetch_1",
          name: "fetch_url",
          arguments: { url: "https://example.com/a" },
          result: null,
          error: "timeout",
          latency_ms: 15000,
        },
      ],
      created_at: iso(5, 25),
      updated_at: iso(5, 10),
    },
  ];
  return {
    id: SEED_RUN_IDS.failedResearch,
    tenant_id: TENANT,
    agent_id: SEED_AGENT_IDS.research,
    thread_id: SEED_THREAD_IDS.research,
    adapter: "langgraph",
    status: "failed",
    input: {
      prompt: "Compare Pinecone, Weaviate, and Qdrant for RAG in 2026.",
    },
    output: null,
    error: "Step fetch failed: fetch_url timed out after 15000ms",
    created_at: iso(5, 30),
    updated_at: iso(5, 10),
    steps,
    messages: [
      {
        id: "msg_fail_0",
        index: 0,
        step_id: null,
        role: "user",
        name: null,
        content: "Compare Pinecone, Weaviate, and Qdrant for RAG in 2026.",
        tool_call_id: null,
        extra: {},
        created_at: iso(5, 30),
      },
      {
        id: "msg_fail_1",
        index: 1,
        step_id: "stp_fail_0",
        role: "assistant",
        name: null,
        content: "Searching recent comparisons…",
        tool_call_id: null,
        extra: {},
        created_at: iso(5, 28),
      },
    ],
    messages_truncated: false,
    checkpoints: [
      {
        id: "cp_fail_0",
        index: 0,
        label: "after_search",
        created_at: iso(5, 27),
      },
    ],
    usage: usageFromSteps(steps),
  };
}

function runningLiveRun(): Run {
  const steps: Step[] = [
    {
      id: "stp_live_0",
      index: 0,
      node: "read_diff",
      status: "succeeded",
      input: { pr: 1842 },
      output: { files_changed: 6 },
      error: null,
      latency_ms: 780,
      tokens_in: 2600,
      tokens_out: 120,
      cost_usd: 0.018,
      tool_calls: [
        {
          id: "tc_read_1",
          name: "read_file",
          arguments: { path: "frontend/lib/api.ts" },
          result: { lines: 205 },
          error: null,
          latency_ms: 40,
        },
      ],
      created_at: iso(0, 8),
      updated_at: iso(0, 7),
    },
    {
      id: "stp_live_1",
      index: 1,
      node: "lint",
      status: "running",
      input: { paths: ["frontend/"] },
      output: null,
      error: null,
      latency_ms: null,
      tokens_in: 400,
      tokens_out: null,
      cost_usd: 0.002,
      tool_calls: [
        {
          id: "tc_lint_1",
          name: "run_linter",
          arguments: { paths: ["frontend/"] },
          result: null,
          error: null,
          latency_ms: null,
        },
      ],
      created_at: iso(0, 5),
      updated_at: iso(0, 2),
    },
  ];
  return {
    id: SEED_RUN_IDS.runningLive,
    tenant_id: TENANT,
    agent_id: SEED_AGENT_IDS.review,
    thread_id: null,
    adapter: "openai_agents",
    status: "running",
    input: {
      prompt: "Review PR #1842: add frontend mock demo mode",
    },
    output: null,
    error: null,
    created_at: iso(0, 8),
    updated_at: iso(0, 2),
    steps,
    messages: [
      {
        id: "msg_live_0",
        index: 0,
        step_id: null,
        role: "user",
        name: null,
        content: "Review PR #1842: add frontend mock demo mode",
        tool_call_id: null,
        extra: {},
        created_at: iso(0, 8),
      },
      {
        id: "msg_live_1",
        index: 1,
        step_id: "stp_live_0",
        role: "assistant",
        name: null,
        content: "Reading changed files and running the linter…",
        tool_call_id: null,
        extra: {},
        created_at: iso(0, 6),
      },
    ],
    messages_truncated: false,
    checkpoints: [],
    usage: usageFromSteps(steps),
  };
}

function cancelledEchoRun(): Run {
  return {
    id: SEED_RUN_IDS.cancelled,
    tenant_id: TENANT,
    agent_id: SEED_AGENT_IDS.echo,
    thread_id: null,
    adapter: "echo",
    status: "cancelled",
    input: { prompt: "ping" },
    output: null,
    error: "cancelled by operator",
    created_at: iso(20),
    updated_at: iso(19, 50),
    steps: [
      {
        id: "stp_cancel_0",
        index: 0,
        node: "echo",
        status: "cancelled",
        input: { prompt: "ping" },
        output: null,
        error: "cancelled",
        latency_ms: 12,
        tokens_in: 4,
        tokens_out: 0,
        cost_usd: 0,
        tool_calls: [],
        created_at: iso(20),
        updated_at: iso(19, 50),
      },
    ],
    messages: [
      {
        id: "msg_cancel_0",
        index: 0,
        step_id: null,
        role: "user",
        name: null,
        content: "ping",
        tool_call_id: null,
        extra: {},
        created_at: iso(20),
      },
    ],
    messages_truncated: false,
    checkpoints: [],
    usage: {
      ...emptyUsage(),
      tokens_in: 4,
      step_count: 1,
      latency_ms: 12,
    },
  };
}

function regressionPairRuns(): Run[] {
  const baselineSteps: Step[] = [
    {
      id: "stp_base_0",
      index: 0,
      node: "echo",
      status: "succeeded",
      input: { prompt: "hello baseline" },
      output: { text: "hello baseline" },
      error: null,
      latency_ms: 18,
      tokens_in: 6,
      tokens_out: 6,
      cost_usd: 0,
      tool_calls: [],
      created_at: iso(10),
      updated_at: iso(10),
    },
  ];
  const candidateSteps: Step[] = [
    {
      id: "stp_cand_0",
      index: 0,
      node: "echo",
      status: "succeeded",
      input: { prompt: "hello baseline" },
      output: { text: "hello baseline" },
      error: null,
      latency_ms: 16,
      tokens_in: 6,
      tokens_out: 6,
      cost_usd: 0,
      tool_calls: [],
      created_at: iso(9),
      updated_at: iso(9),
    },
  ];
  return [
    {
      id: SEED_RUN_IDS.succeededBaseline,
      tenant_id: TENANT,
      agent_id: SEED_AGENT_IDS.echo,
      thread_id: null,
      adapter: "echo",
      status: "succeeded",
      input: { prompt: "hello baseline" },
      output: { text: "hello baseline" },
      error: null,
      created_at: iso(10),
      updated_at: iso(10),
      steps: baselineSteps,
      messages: [
        {
          id: "msg_base_0",
          index: 0,
          step_id: null,
          role: "user",
          name: null,
          content: "hello baseline",
          tool_call_id: null,
          extra: {},
          created_at: iso(10),
        },
        {
          id: "msg_base_1",
          index: 1,
          step_id: "stp_base_0",
          role: "assistant",
          name: null,
          content: "hello baseline",
          tool_call_id: null,
          extra: {},
          created_at: iso(10),
        },
      ],
      messages_truncated: false,
      checkpoints: [],
      usage: usageFromSteps(baselineSteps),
    },
    {
      id: SEED_RUN_IDS.succeededCandidate,
      tenant_id: TENANT,
      agent_id: SEED_AGENT_IDS.echo,
      thread_id: null,
      adapter: "echo",
      status: "succeeded",
      input: { prompt: "hello baseline" },
      output: { text: "hello baseline" },
      error: null,
      created_at: iso(9),
      updated_at: iso(9),
      steps: candidateSteps,
      messages: [
        {
          id: "msg_cand_0",
          index: 0,
          step_id: null,
          role: "user",
          name: null,
          content: "hello baseline",
          tool_call_id: null,
          extra: {},
          created_at: iso(9),
        },
        {
          id: "msg_cand_1",
          index: 1,
          step_id: "stp_cand_0",
          role: "assistant",
          name: null,
          content: "hello baseline",
          tool_call_id: null,
          extra: {},
          created_at: iso(9),
        },
      ],
      messages_truncated: false,
      checkpoints: [],
      usage: usageFromSteps(candidateSteps),
    },
  ];
}

export function buildSeedRuns(): Run[] {
  const okSteps = supportSucceededSteps();
  const ok: Run = {
    id: SEED_RUN_IDS.succeededSupport,
    tenant_id: TENANT,
    agent_id: SEED_AGENT_IDS.support,
    thread_id: SEED_THREAD_IDS.refund,
    adapter: "langchain",
    status: "succeeded",
    input: { prompt: "Where is my order AC-94821?" },
    output: {
      reply:
        "Your order AC-94821 shipped via UPS (1Z999AA10123456784) and is due Sep 20.",
    },
    error: null,
    created_at: iso(3, 10),
    updated_at: iso(3, 7),
    steps: okSteps,
    messages: supportSucceededMessages(),
    messages_truncated: false,
    checkpoints: [
      {
        id: "cp_ok_0",
        index: 0,
        label: "after_tools",
        created_at: iso(3, 8),
      },
    ],
    usage: usageFromSteps(okSteps),
  };

  return [
    runningLiveRun(),
    waitingApprovalRun(),
    ok,
    ...regressionPairRuns(),
    failedResearchRun(),
    cancelledEchoRun(),
  ];
}

export function buildSeedThreadMessages(): Record<string, ThreadMessage[]> {
  const supportMsgs = supportSucceededMessages().map((m) => ({
    ...m,
    run_id: SEED_RUN_IDS.succeededSupport,
  }));
  const waitMsgs: ThreadMessage[] = [
    {
      id: "msg_wait_0",
      index: 0,
      step_id: null,
      role: "user",
      name: null,
      content: "I want a full refund for order AC-94821 — I changed my mind.",
      tool_call_id: null,
      extra: {},
      created_at: iso(1, 40),
      run_id: SEED_RUN_IDS.waitingApproval,
    },
    {
      id: "msg_wait_1",
      index: 1,
      step_id: "stp_wait_1",
      role: "assistant",
      name: null,
      content:
        "Order AC-94821 totals $189.00. Policy requires manager approval for full refunds over $100 when the reason is change-of-mind.",
      tool_call_id: null,
      extra: {},
      created_at: iso(1, 36),
      run_id: SEED_RUN_IDS.waitingApproval,
    },
  ];
  return {
    [SEED_THREAD_IDS.refund]: [...supportMsgs, ...waitMsgs],
    [SEED_THREAD_IDS.research]: [
      {
        id: "msg_fail_0",
        index: 0,
        step_id: null,
        role: "user",
        name: null,
        content: "Compare Pinecone, Weaviate, and Qdrant for RAG in 2026.",
        tool_call_id: null,
        extra: {},
        created_at: iso(5, 30),
        run_id: SEED_RUN_IDS.failedResearch,
      },
      {
        id: "msg_fail_1",
        index: 1,
        step_id: "stp_fail_0",
        role: "assistant",
        name: null,
        content: "Searching recent comparisons…",
        tool_call_id: null,
        extra: {},
        created_at: iso(5, 28),
        run_id: SEED_RUN_IDS.failedResearch,
      },
    ],
  };
}

export function buildSeedAudit(): Record<string, RunAuditEvent[]> {
  return {
    [SEED_RUN_IDS.cancelled]: [
      {
        id: "aud_cancel_1",
        tenant_id: TENANT,
        run_id: SEED_RUN_IDS.cancelled,
        action: "cancel",
        actor_subject: "demo-operator",
        actor_role: "admin",
        detail: { reason: "smoke test cancel" },
        created_at: iso(19, 50),
      },
    ],
  };
}

export function buildSeedRegressions(): {
  executions: Record<string, RegressionExecution>;
  results: Record<string, RegressionExecutionResults>;
} {
  return { executions: {}, results: {} };
}

export const MOCK_TENANT_ID = TENANT;
