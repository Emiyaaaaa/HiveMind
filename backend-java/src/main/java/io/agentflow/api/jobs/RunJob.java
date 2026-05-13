package io.agentflow.api.jobs;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.time.Instant;

/**
 * Payload pushed onto {@code agentflow:jobs:runs}. The Python worker decodes
 * the same shape (see {@code backend/app/worker/runner.py}).
 */
public record RunJob(
        @JsonProperty("run_id") String runId,
        @JsonProperty("agent_id") String agentId,
        String adapter,
        @JsonProperty("enqueued_at") Instant enqueuedAt) {
}
