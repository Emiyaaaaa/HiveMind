package io.agentflow.api.dto;

import io.agentflow.api.entity.RunAuditEventEntity;
import java.time.Instant;
import java.util.Map;

public class RunAuditEventResponse {

    private String id;
    private String tenantId;
    private String runId;
    private String action;
    private String actorSubject;
    private String actorRole;
    private Map<String, Object> detail;
    private Instant createdAt;

    public static RunAuditEventResponse fromEntity(RunAuditEventEntity entity) {
        RunAuditEventResponse dto = new RunAuditEventResponse();
        dto.id = entity.getId();
        dto.tenantId = entity.getTenantId();
        dto.runId = entity.getRunId();
        dto.action = entity.getAction();
        dto.actorSubject = entity.getActorSubject();
        dto.actorRole = entity.getActorRole();
        dto.detail = entity.getDetail();
        dto.createdAt = entity.getCreatedAt();
        return dto;
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

    public String getAction() {
        return action;
    }

    public String getActorSubject() {
        return actorSubject;
    }

    public String getActorRole() {
        return actorRole;
    }

    public Map<String, Object> getDetail() {
        return detail;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }
}
