package io.agentflow.api.dto;

public class QuotaConfigRequest {

    private String period = "month";
    private Integer maxTokens;
    private Double maxCostUsd;
    private Boolean enforce;

    public String getPeriod() {
        return period;
    }

    public void setPeriod(String period) {
        this.period = period;
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

    public Boolean getEnforce() {
        return enforce;
    }

    public void setEnforce(Boolean enforce) {
        this.enforce = enforce;
    }
}
