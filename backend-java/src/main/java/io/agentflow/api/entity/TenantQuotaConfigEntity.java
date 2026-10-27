package io.agentflow.api.entity;

import jakarta.persistence.Entity;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;

@Entity
@Table(
        name = "tenant_quota_configs",
        uniqueConstraints =
                @UniqueConstraint(
                        name = "uq_tenant_quota_configs_tenant",
                        columnNames = {"tenant_id"}))
public class TenantQuotaConfigEntity extends AbstractQuotaConfigEntity {}
