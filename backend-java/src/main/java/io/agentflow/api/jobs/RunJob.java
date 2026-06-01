package io.agentflow.api.jobs;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.time.Instant;
import java.util.Map;

/**
 * Payload pushed onto {@code agentflow:jobs:runs}. The Python worker decodes
 * the same shape (see {@code backend/app/worker/runner.py}).
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record RunJob(
        @JsonProperty("run_id") String runId,
        @JsonProperty("agent_id") String agentId,
        String adapter,
        @JsonProperty("enqueued_at") Instant enqueuedAt,
        @JsonProperty("trace_context") Map<String, String> traceContext) {

    public RunJob(String runId, String agentId, String adapter, Instant enqueuedAt) {
        this(runId, agentId, adapter, enqueuedAt, null);
    }
}
