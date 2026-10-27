package io.agentflow.api.entity;

import com.github.f4b6a3.ulid.UlidCreator;
import jakarta.persistence.Column;
import jakarta.persistence.Id;
import jakarta.persistence.MappedSuperclass;
import jakarta.persistence.PrePersist;
import jakarta.persistence.PreUpdate;
import java.time.Instant;

/** Shared counters for tenant, project, and agent quota usage rows. */
@MappedSuperclass
public abstract class AbstractQuotaUsageEntity {

    @Id
    @Column(length = 26)
    private String id;

    @Column(name = "tenant_id", nullable = false, length = 64)
    private String tenantId = "default";

    @Column(nullable = false, length = 16)
    private String period = "month";

    @Column(name = "period_key", nullable = false, length = 32)
    private String periodKey;

    @Column(name = "tokens_in", nullable = false)
    private int tokensIn;

    @Column(name = "tokens_out", nullable = false)
    private int tokensOut;

    @Column(name = "cost_usd", nullable = false)
    private double costUsd;

    @Column(name = "run_count", nullable = false)
    private int runCount;

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

    public String getPeriodKey() {
        return periodKey;
    }

    public void setPeriodKey(String periodKey) {
        this.periodKey = periodKey;
    }

    public int getTokensIn() {
        return tokensIn;
    }

    public void setTokensIn(int tokensIn) {
        this.tokensIn = tokensIn;
    }

    public int getTokensOut() {
        return tokensOut;
    }

    public void setTokensOut(int tokensOut) {
        this.tokensOut = tokensOut;
    }

    public double getCostUsd() {
        return costUsd;
    }

    public void setCostUsd(double costUsd) {
        this.costUsd = costUsd;
    }

    public int getRunCount() {
        return runCount;
    }

    public void setRunCount(int runCount) {
        this.runCount = runCount;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }

    public int totalTokens() {
        return tokensIn + tokensOut;
    }
}
