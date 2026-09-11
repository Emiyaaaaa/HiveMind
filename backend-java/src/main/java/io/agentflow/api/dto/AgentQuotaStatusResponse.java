package io.agentflow.api.dto;

import java.time.Instant;

public class AgentQuotaStatusResponse {

    private String agentId;
    private boolean active;
    private boolean enforce;
    private String period;
    private String periodKey;
    private Instant periodStart;
    private Instant periodEnd;
    private Integer maxTokens;
    private Double maxCostUsd;
    private int usedTokens;
    private int usedTokensIn;
    private int usedTokensOut;
    private double usedCostUsd;
    private int runCount;
    private Integer remainingTokens;
    private Double remainingCostUsd;
    private boolean exceeded;

    public String getAgentId() {
        return agentId;
    }

    public void setAgentId(String agentId) {
        this.agentId = agentId;
    }

    public boolean isActive() {
        return active;
    }

    public void setActive(boolean active) {
        this.active = active;
    }

    public boolean isEnforce() {
        return enforce;
    }

    public void setEnforce(boolean enforce) {
        this.enforce = enforce;
    }

    public String getPeriod() {
        return period;
    }

    public void setPeriod(String period) {
        this.period = period;
    }

    public String getPeriodKey() {
        return periodKey;
    }

    public void setPeriodKey(String periodKey) {
        this.periodKey = periodKey;
    }

    public Instant getPeriodStart() {
        return periodStart;
    }

    public void setPeriodStart(Instant periodStart) {
        this.periodStart = periodStart;
    }

    public Instant getPeriodEnd() {
        return periodEnd;
    }

    public void setPeriodEnd(Instant periodEnd) {
        this.periodEnd = periodEnd;
    }

    public Integer getMaxTokens() {
        return maxTokens;
    }

    public void setMaxTokens(Integer maxTokens) {
        this.maxTokens = maxTokens;
    }

    public Double getMaxCostUsd() {
        return maxCostUsd;
    }

    public void setMaxCostUsd(Double maxCostUsd) {
        this.maxCostUsd = maxCostUsd;
    }

    public int getUsedTokens() {
        return usedTokens;
    }

    public void setUsedTokens(int usedTokens) {
        this.usedTokens = usedTokens;
    }

    public int getUsedTokensIn() {
        return usedTokensIn;
    }

    public void setUsedTokensIn(int usedTokensIn) {
        this.usedTokensIn = usedTokensIn;
    }

    public int getUsedTokensOut() {
        return usedTokensOut;
    }

    public void setUsedTokensOut(int usedTokensOut) {
        this.usedTokensOut = usedTokensOut;
    }

    public double getUsedCostUsd() {
        return usedCostUsd;
    }

    public void setUsedCostUsd(double usedCostUsd) {
        this.usedCostUsd = usedCostUsd;
    }

    public int getRunCount() {
        return runCount;
    }

    public void setRunCount(int runCount) {
        this.runCount = runCount;
    }

    public Integer getRemainingTokens() {
        return remainingTokens;
    }

    public void setRemainingTokens(Integer remainingTokens) {
        this.remainingTokens = remainingTokens;
    }

    public Double getRemainingCostUsd() {
        return remainingCostUsd;
    }

    public void setRemainingCostUsd(Double remainingCostUsd) {
        this.remainingCostUsd = remainingCostUsd;
    }

    public boolean isExceeded() {
        return exceeded;
    }

    public void setExceeded(boolean exceeded) {
        this.exceeded = exceeded;
    }
}
