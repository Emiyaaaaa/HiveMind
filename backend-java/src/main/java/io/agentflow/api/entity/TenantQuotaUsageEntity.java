package io.agentflow.api.entity;

import jakarta.persistence.Entity;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;

@Entity
@Table(
        name = "tenant_quota_usage",
        uniqueConstraints =
                @UniqueConstraint(
                        name = "uq_tenant_quota_usage_period",
                        columnNames = {"tenant_id", "period_key"}))
public class TenantQuotaUsageEntity extends AbstractQuotaUsageEntity {}
