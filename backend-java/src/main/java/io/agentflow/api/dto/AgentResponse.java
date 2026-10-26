package io.agentflow.api.dto;

import io.agentflow.api.entity.AgentEntity;
import java.time.Instant;
import java.util.Map;

public class AgentResponse {

    private String id;
    private String tenantId;
    private String name;
    private String description;
    private String adapter;
    private Map<String, Object> config;
    private int version;
    private Instant createdAt;
    private Instant updatedAt;

    public static AgentResponse fromEntity(AgentEntity entity) {
        AgentResponse dto = new AgentResponse();
        dto.id = entity.getId();
        dto.tenantId = entity.getTenantId();
        dto.name = entity.getName();
        dto.description = entity.getDescription();
        dto.adapter = entity.getAdapter();
        dto.config = entity.getConfig();
        dto.version = entity.getVersion();
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

    public String getName() {
        return name;
    }

    public String getDescription() {
        return description;
    }

    public String getAdapter() {
        return adapter;
    }

    public Map<String, Object> getConfig() {
        return config;
    }

    public int getVersion() {
        return version;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }
}
