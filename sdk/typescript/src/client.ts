import type {
  AgentFlowClientOptions,
  Run,
  RunCreateRequest,
} from "./types.js";

function authHeaders(apiKey?: string): HeadersInit {
  return apiKey ? { "X-Api-Key": apiKey } : {};
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${text}`);
  }
  return (await response.json()) as T;
}

export class AgentFlowClient {
  private readonly baseUrl: string;
  private readonly apiKey?: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: AgentFlowClientOptions = {}) {
    this.baseUrl = (options.baseUrl ?? "http://localhost:8000").replace(/\/$/, "");
    this.apiKey = options.apiKey;
    this.fetchImpl = options.fetch ?? fetch;
  }

  async createRun(request: RunCreateRequest): Promise<Run> {
    const response = await this.fetchImpl(`${this.baseUrl}/v1/runs`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...authHeaders(this.apiKey),
      },
      body: JSON.stringify(request),
    });
    return readJson<Run>(response);
  }

  async getRun(runId: string): Promise<Run> {
    const response = await this.fetchImpl(`${this.baseUrl}/v1/runs/${runId}`, {
      headers: authHeaders(this.apiKey),
    });
    return readJson<Run>(response);
  }

  async cancelRun(runId: string): Promise<void> {
    const response = await this.fetchImpl(`${this.baseUrl}/v1/runs/${runId}/cancel`, {
      method: "POST",
      headers: authHeaders(this.apiKey),
    });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(`${response.status} ${response.statusText}: ${text}`);
    }
  }

  async health(): Promise<{ status: string; version: string; adapters: string[] }> {
    const response = await this.fetchImpl(`${this.baseUrl}/v1/health`);
    return readJson(response);
  }
}
