package io.agentflow.api.dto;

public class RetentionPurgeResponse {

    private String tenantId;
    private int runsPurged;
    private long messagesDeleted;
    private long checkpointsDeleted;

    public RetentionPurgeResponse(
            String tenantId, int runsPurged, long messagesDeleted, long checkpointsDeleted) {
        this.tenantId = tenantId;
        this.runsPurged = runsPurged;
        this.messagesDeleted = messagesDeleted;
        this.checkpointsDeleted = checkpointsDeleted;
    }

    public String getTenantId() {
        return tenantId;
    }

    public int getRunsPurged() {
        return runsPurged;
    }

    public long getMessagesDeleted() {
        return messagesDeleted;
    }

    public long getCheckpointsDeleted() {
        return checkpointsDeleted;
    }
}
