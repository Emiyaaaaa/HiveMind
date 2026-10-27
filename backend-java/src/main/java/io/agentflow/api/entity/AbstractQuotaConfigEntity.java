package io.agentflow.api.entity;

import com.github.f4b6a3.ulid.UlidCreator;
import jakarta.persistence.Column;
import jakarta.persistence.Id;
import jakarta.persistence.MappedSuperclass;
import jakarta.persistence.PrePersist;
import jakarta.persistence.PreUpdate;
import java.time.Instant;

/** Shared limit columns for tenant and project quota configuration rows. */
@MappedSuperclass
public abstract class AbstractQuotaConfigEntity {

    @Id
    @Column(length = 26)
    private String id;

    @Column(name = "tenant_id", nullable = false, length = 64)
    private String tenantId = "default";

    @Column(nullable = false, length = 16)
    private String period = "month";

    @Column(name = "max_tokens")
    private Integer maxTokens;

    @Column(name = "max_cost_usd")
    private Double maxCostUsd;

    @Column(nullable = false)
    private boolean enforce = true;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    @PrePersist
    void onCreate() {
        if (id == null) {
            id = UlidCreator.getUlid().toString();
        }
        Instant now = Instant.now();
        if (createdAt == null) {
            createdAt = now;
        }
        updatedAt = now;
    }

    @PreUpdate
    void onUpdate() {
        updatedAt = Instant.now();
    }

    public String getId() {
        return id;
    }

    public void setId(String id) {
        this.id = id;
    }

    public String getTenantId() {
        return tenantId;
    }

    public void setTenantId(String tenantId) {
        this.tenantId = tenantId;
    }

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

    public boolean isEnforce() {
        return enforce;
    }

    public void setEnforce(boolean enforce) {
        this.enforce = enforce;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }
}
