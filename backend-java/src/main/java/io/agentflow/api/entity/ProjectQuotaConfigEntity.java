package io.agentflow.api.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;

@Entity
@Table(
        name = "project_quota_configs",
        uniqueConstraints =
                @UniqueConstraint(
                        name = "uq_project_quota_configs_project",
                        columnNames = {"project_id"}))
public class ProjectQuotaConfigEntity extends AbstractQuotaConfigEntity {

    @Column(name = "project_id", nullable = false, length = 26)
    private String projectId;

    public String getProjectId() {
        return projectId;
    }

    public void setProjectId(String projectId) {
        this.projectId = projectId;
    }
}
