package io.agentflow.api.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.time.Instant;
import java.util.List;

public record BatchResponse(
        String id,
        @JsonProperty("agent_id") String agentId,
        String status,
        int total,
        int completed,
        @JsonProperty("run_ids") List<String> runIds,
        @JsonProperty("created_at") Instant createdAt) {}
