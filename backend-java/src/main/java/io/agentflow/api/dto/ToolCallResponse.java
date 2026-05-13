package io.agentflow.api.dto;

import io.agentflow.api.entity.ToolCallEntity;
import java.util.Map;

public class ToolCallResponse {

    private String id;
    private String name;
    private Map<String, Object> arguments;
    private Map<String, Object> result;
    private String error;
    private Integer latencyMs;

    public static ToolCallResponse fromEntity(ToolCallEntity entity) {
        ToolCallResponse dto = new ToolCallResponse();
        dto.id = entity.getId();
        dto.name = entity.getName();
        dto.arguments = entity.getArguments();
        dto.result = entity.getResult();
        dto.error = entity.getError();
        dto.latencyMs = entity.getLatencyMs();
        return dto;
    }

    public String getId() {
        return id;
    }

    public String getName() {
        return name;
    }

    public Map<String, Object> getArguments() {
        return arguments;
    }

    public Map<String, Object> getResult() {
        return result;
    }

    public String getError() {
        return error;
    }

    public Integer getLatencyMs() {
        return latencyMs;
    }
}
