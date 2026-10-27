package io.agentflow.api.repository;

import io.agentflow.api.entity.TenantQuotaConfigEntity;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

public interface TenantQuotaConfigRepository extends JpaRepository<TenantQuotaConfigEntity, String> {

    Optional<TenantQuotaConfigEntity> findByTenantId(String tenantId);
}
