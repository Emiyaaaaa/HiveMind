package io.agentflow.api.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;

@Entity
@Table(
        name = "agent_quota_usage",
        uniqueConstraints =
                @UniqueConstraint(
                        name = "uq_agent_quota_usage_period",
                        columnNames = {"agent_id", "period_key"}))
public class AgentQuotaUsageEntity extends AbstractQuotaUsageEntity {

    @Column(name = "project_id", length = 26)
    private String projectId;

    @Column(name = "agent_id", nullable = false, length = 26)
    private String agentId;

    public String getProjectId() {
        return projectId;
    }

    public void setProjectId(String projectId) {
        this.projectId = projectId;
    }

    public String getAgentId() {
        return agentId;
    }

    public void setAgentId(String agentId) {
        this.agentId = agentId;
    }
}
