package io.agentflow.api.dto;

import io.agentflow.api.entity.ThreadEntity;
import java.time.Instant;

public class ThreadResponse {

    private String id;
    private String tenantId;
    private String projectId;
    private String agentId;
    private String userId;
    private String title;
    private Instant createdAt;
    private Instant updatedAt;

    public static ThreadResponse fromEntity(ThreadEntity entity) {
        ThreadResponse dto = new ThreadResponse();
        dto.id = entity.getId();
        dto.tenantId = entity.getTenantId();
        dto.projectId = entity.getProjectId();
        dto.agentId = entity.getAgentId();
        dto.userId = entity.getUserId();
        dto.title = entity.getTitle();
        dto.createdAt = entity.getCreatedAt();
        dto.updatedAt = entity.getUpdatedAt();
        return dto;
    }

    public String getId() {
        return id;
    }

    public String getTenantId() {
        return tenantId;
    }

    public String getProjectId() {
        return projectId;
    }

    public String getAgentId() {
        return agentId;
    }

    public String getUserId() {
        return userId;
    }

    public String getTitle() {
        return title;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }
}
