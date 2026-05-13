package io.agentflow.api.dto;

import io.agentflow.api.entity.MessageEntity;
import java.time.Instant;
import java.util.Map;

public class MessageResponse {

    private String id;
    private int index;
    private String role;
    private String name;
    private String content;
    private String toolCallId;
    private Map<String, Object> extra;
    private Instant createdAt;

    public static MessageResponse fromEntity(MessageEntity entity) {
        MessageResponse dto = new MessageResponse();
        dto.id = entity.getId();
        dto.index = entity.getIndex();
        dto.role = entity.getRole();
        dto.name = entity.getName();
        dto.content = entity.getContent();
        dto.toolCallId = entity.getToolCallId();
        dto.extra = entity.getExtra();
        dto.createdAt = entity.getCreatedAt();
        return dto;
    }

    public String getId() {
        return id;
    }

    public int getIndex() {
        return index;
    }

    public String getRole() {
        return role;
    }

    public String getName() {
        return name;
    }

    public String getContent() {
        return content;
    }

    public String getToolCallId() {
        return toolCallId;
    }

    public Map<String, Object> getExtra() {
        return extra;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }
}
