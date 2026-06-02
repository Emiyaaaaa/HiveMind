package io.agentflow.api.dto;

import io.agentflow.api.entity.RunStatus;
import io.agentflow.api.entity.StepEntity;
import java.time.Instant;
import java.util.List;
import java.util.Map;

public class StepResponse {

    private String id;
    private int index;
    private String node;
    private RunStatus status;
    private Map<String, Object> input;
    private Map<String, Object> output;
    private String error;
    private Integer latencyMs;
    private Integer tokensIn;
    private Integer tokensOut;
    private Double costUsd;
    private List<ToolCallResponse> toolCalls;
    private Instant createdAt;
    private Instant updatedAt;

    public static StepResponse fromEntity(StepEntity entity, List<ToolCallResponse> toolCalls) {
        StepResponse dto = new StepResponse();
        dto.id = entity.getId();
        dto.index = entity.getIndex();
        dto.node = entity.getNode();
        dto.status = entity.getStatus();
        dto.input = entity.getInput();
        dto.output = entity.getOutput();
        dto.error = entity.getError();
        dto.latencyMs = entity.getLatencyMs();
        dto.tokensIn = entity.getTokensIn();
        dto.tokensOut = entity.getTokensOut();
        dto.costUsd = entity.getCostUsd();
        dto.toolCalls = toolCalls;
        dto.createdAt = entity.getCreatedAt();
        dto.updatedAt = entity.getUpdatedAt();
        return dto;
    }

    public String getId() {
        return id;
    }

    public int getIndex() {
        return index;
    }

    public String getNode() {
        return node;
    }

    public RunStatus getStatus() {
        return status;
    }

    public Map<String, Object> getInput() {
        return input;
    }

    public Map<String, Object> getOutput() {
        return output;
    }

    public String getError() {
        return error;
    }

    public Integer getLatencyMs() {
        return latencyMs;
    }

    public Integer getTokensIn() {
        return tokensIn;
    }

    public Integer getTokensOut() {
        return tokensOut;
    }

    public Double getCostUsd() {
        return costUsd;
    }

    public List<ToolCallResponse> getToolCalls() {
        return toolCalls;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }
}
