package io.agentflow.api.service;

public class AgentQuotaExceededException extends RuntimeException {

    private final String agentId;
    private final String periodKey;
    private final String reason;

    public AgentQuotaExceededException(
            String agentId, String periodKey, String reason, String message) {
        super(message);
        this.agentId = agentId;
        this.periodKey = periodKey;
        this.reason = reason;
    }

    public String getAgentId() {
        return agentId;
    }

    public String getPeriodKey() {
        return periodKey;
    }

    public String getReason() {
        return reason;
    }
}
