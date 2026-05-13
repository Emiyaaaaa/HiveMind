package io.agentflow.api.dto;

import io.agentflow.api.entity.CheckpointEntity;
import java.time.Instant;

public class CheckpointResponse {

    private String id;
    private int index;
    private String label;
    private Instant createdAt;

    public static CheckpointResponse fromEntity(CheckpointEntity entity) {
        CheckpointResponse dto = new CheckpointResponse();
        dto.id = entity.getId();
        dto.index = entity.getIndex();
        dto.label = entity.getLabel();
        dto.createdAt = entity.getCreatedAt();
        return dto;
    }

    public String getId() {
        return id;
    }

    public int getIndex() {
        return index;
    }

    public String getLabel() {
        return label;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }
}
