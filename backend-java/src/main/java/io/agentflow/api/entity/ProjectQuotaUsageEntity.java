package io.agentflow.api.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;

@Entity
@Table(
        name = "project_quota_usage",
        uniqueConstraints =
                @UniqueConstraint(
                        name = "uq_project_quota_usage_period",
                        columnNames = {"project_id", "period_key"}))
public class ProjectQuotaUsageEntity extends AbstractQuotaUsageEntity {

    @Column(name = "project_id", nullable = false, length = 26)
    private String projectId;

    public String getProjectId() {
        return projectId;
    }

    public void setProjectId(String projectId) {
        this.projectId = projectId;
    }
}
