package io.agentflow.api.dto;

import io.agentflow.api.entity.AttachmentEntity;
import java.time.Instant;

public class AttachmentResponse {

    private String id;
    private String tenantId;
    private String runId;
    private String messageId;
    private String mediaType;
    private String filename;
    private long sizeBytes;
    private String sha256;
    private String caption;
    private String url;
    private Instant createdAt;
    private Instant updatedAt;

    public static AttachmentResponse fromEntity(AttachmentEntity entity) {
        AttachmentResponse response = new AttachmentResponse();
        response.id = entity.getId();
        response.tenantId = entity.getTenantId();
        response.runId = entity.getRunId();
        response.messageId = entity.getMessageId();
        response.mediaType = entity.getMediaType();
        response.filename = entity.getFilename();
        response.sizeBytes = entity.getSizeBytes();
        response.sha256 = entity.getSha256();
        response.caption = entity.getCaption();
        response.url = "/v1/attachments/" + entity.getId();
        response.createdAt = entity.getCreatedAt();
        response.updatedAt = entity.getUpdatedAt();
        return response;
    }

    public String getId() {
        return id;
    }

    public String getTenantId() {
        return tenantId;
    }

    public String getRunId() {
        return runId;
    }

    public String getMessageId() {
        return messageId;
    }

    public String getMediaType() {
        return mediaType;
    }

    public String getFilename() {
        return filename;
    }

    public long getSizeBytes() {
        return sizeBytes;
    }

    public String getSha256() {
        return sha256;
    }

    public String getCaption() {
        return caption;
    }

    public String getUrl() {
        return url;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }
}
