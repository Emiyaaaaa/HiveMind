package io.agentflow.api.dto;

import io.agentflow.api.entity.AgentVersionEntity;
import java.time.Instant;
import java.util.Map;

public class AgentVersionResponse {

    private String id;
    private String agentId;
    private int version;
    private String description;
    private String adapter;
    private Map<String, Object> config;
    private String note;
    private Instant createdAt;

    public static AgentVersionResponse fromEntity(AgentVersionEntity entity) {
        AgentVersionResponse dto = new AgentVersionResponse();
        dto.id = entity.getId();
        dto.agentId = entity.getAgentId();
        dto.version = entity.getVersion();
        dto.description = entity.getDescription();
        dto.adapter = entity.getAdapter();
        dto.config = entity.getConfig();
        dto.note = entity.getNote();
        dto.createdAt = entity.getCreatedAt();
        return dto;
    }

    public String getId() {
        return id;
    }

    public String getAgentId() {
        return agentId;
    }

    public int getVersion() {
        return version;
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

    public String getNote() {
        return note;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }
}
