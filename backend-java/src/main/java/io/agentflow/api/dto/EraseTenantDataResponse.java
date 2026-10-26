package io.agentflow.api.dto;

public class EraseTenantDataResponse {

    private String tenantId;
    private int runsProcessed;
    private long messagesDeleted;
    private long checkpointsDeleted;

    public EraseTenantDataResponse(
            String tenantId, int runsProcessed, long messagesDeleted, long checkpointsDeleted) {
        this.tenantId = tenantId;
        this.runsProcessed = runsProcessed;
        this.messagesDeleted = messagesDeleted;
        this.checkpointsDeleted = checkpointsDeleted;
    }

    public String getTenantId() {
        return tenantId;
    }

    public int getRunsProcessed() {
        return runsProcessed;
    }

    public long getMessagesDeleted() {
        return messagesDeleted;
    }

    public long getCheckpointsDeleted() {
        return checkpointsDeleted;
    }
}
