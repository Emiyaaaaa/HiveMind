package io.agentflow.api.service;

public class AgentQuotaExceededException extends RuntimeException {

    private final String scope;
    private final String scopeId;
    private final String agentId;
    private final String periodKey;
    private final String reason;

    public AgentQuotaExceededException(
            String scope,
            String scopeId,
            String agentId,
            String periodKey,
            String reason,
            String message) {
        super(message);
        this.scope = scope;
        this.scopeId = scopeId;
        this.agentId = agentId;
        this.periodKey = periodKey;
        this.reason = reason;
    }

    public String getScope() {
        return scope;
    }

    public String getScopeId() {
        return scopeId;
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
