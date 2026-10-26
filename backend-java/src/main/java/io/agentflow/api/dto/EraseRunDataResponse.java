package io.agentflow.api.dto;

public class EraseRunDataResponse {

    private String runId;
    private long messagesDeleted;
    private long checkpointsDeleted;

    public EraseRunDataResponse(String runId, long messagesDeleted, long checkpointsDeleted) {
        this.runId = runId;
        this.messagesDeleted = messagesDeleted;
        this.checkpointsDeleted = checkpointsDeleted;
    }

    public String getRunId() {
        return runId;
    }

    public long getMessagesDeleted() {
        return messagesDeleted;
    }

    public long getCheckpointsDeleted() {
        return checkpointsDeleted;
    }
}
