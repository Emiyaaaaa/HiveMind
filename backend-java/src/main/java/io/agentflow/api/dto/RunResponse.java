package io.agentflow.api.dto;

import io.agentflow.api.entity.RunEntity;
import io.agentflow.api.entity.RunStatus;
import java.time.Instant;
import java.util.List;
import java.util.Map;

public class RunResponse {

    private String id;
    private String agentId;
    private String adapter;
    private RunStatus status;
    private Map<String, Object> input;
    private Map<String, Object> output;
    private String error;
    private Instant createdAt;
    private Instant updatedAt;
    private List<StepResponse> steps;
    private List<MessageResponse> messages;
    private List<CheckpointResponse> checkpoints;
    private RunUsage usage = RunUsage.empty();

    /** Run header only; nested collections are empty (used by {@code GET /v1/runs}). */
    public static RunResponse fromEntity(RunEntity entity) {
        RunUsage stored = RunUsage.fromMetadata(entity.getMetadata());
        RunUsage usage = stored != null ? stored : RunUsage.empty();
        return fromEntity(entity, List.of(), List.of(), List.of(), usage);
    }

    public static RunResponse fromEntity(
            RunEntity entity,
            List<StepResponse> steps,
            List<MessageResponse> messages,
            List<CheckpointResponse> checkpoints) {
        RunUsage usage = steps.isEmpty()
                ? RunUsage.fromMetadata(entity.getMetadata())
                : RunUsage.fromSteps(steps);
        if (usage == null) {
            usage = RunUsage.empty();
        }
        return fromEntity(entity, steps, messages, checkpoints, usage);
    }

    public static RunResponse fromEntity(
            RunEntity entity,
            List<StepResponse> steps,
            List<MessageResponse> messages,
            List<CheckpointResponse> checkpoints,
            RunUsage usage) {
        RunResponse dto = new RunResponse();
        dto.id = entity.getId();
        dto.agentId = entity.getAgentId();
        dto.adapter = entity.getAdapter();
        dto.status = entity.getStatus();
        dto.input = entity.getInput();
        dto.output = entity.getOutput();
        dto.error = entity.getError();
        dto.createdAt = entity.getCreatedAt();
        dto.updatedAt = entity.getUpdatedAt();
        dto.steps = steps;
        dto.messages = messages;
        dto.checkpoints = checkpoints;
        dto.usage = usage;
        return dto;
    }

    public String getId() {
        return id;
    }

    public String getAgentId() {
        return agentId;
    }

    public String getAdapter() {
        return adapter;
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

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }

    public List<StepResponse> getSteps() {
        return steps;
    }

    public List<MessageResponse> getMessages() {
        return messages;
    }

    public List<CheckpointResponse> getCheckpoints() {
        return checkpoints;
    }

    public RunUsage getUsage() {
        return usage;
    }
}
