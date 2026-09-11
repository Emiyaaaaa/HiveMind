package io.agentflow.api.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import io.agentflow.api.entity.RunScheduleEntity;
import java.time.Instant;
import java.util.Map;

public record ScheduleResponse(
        String id,
        @JsonProperty("agent_id") String agentId,
        String name,
        String cron,
        @JsonProperty("interval_seconds") Integer intervalSeconds,
        String timezone,
        Map<String, Object> input,
        Map<String, Object> metadata,
        String adapter,
        boolean enabled,
        @JsonProperty("next_run_at") Instant nextRunAt,
        @JsonProperty("last_run_at") Instant lastRunAt,
        @JsonProperty("last_run_id") String lastRunId,
        @JsonProperty("created_at") Instant createdAt,
        @JsonProperty("updated_at") Instant updatedAt) {

    public static ScheduleResponse fromEntity(RunScheduleEntity entity) {
        return new ScheduleResponse(
                entity.getId(),
                entity.getAgentId(),
                entity.getName(),
                entity.getCron(),
                entity.getIntervalSeconds(),
                entity.getTimezone(),
                entity.getInput(),
                entity.getMetadata(),
                entity.getAdapter(),
                entity.isEnabled(),
                entity.getNextRunAt(),
                entity.getLastRunAt(),
                entity.getLastRunId(),
                entity.getCreatedAt(),
                entity.getUpdatedAt());
    }
}
