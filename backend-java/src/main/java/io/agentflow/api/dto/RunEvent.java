package io.agentflow.api.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.time.Instant;
import java.util.Map;

/**
 * Wire format for SSE messages, mirroring {@code app.schemas.run.RunEvent}.
 * The {@code type} is also used as the SSE {@code event} field.
 */
public record RunEvent(
        String type,
        @JsonProperty("run_id") String runId,
        Instant at,
        Map<String, Object> data) {
}
