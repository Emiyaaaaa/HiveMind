package io.agentflow.api.repository;

import io.agentflow.api.entity.TenantQuotaUsageEntity;
import jakarta.persistence.LockModeType;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface TenantQuotaUsageRepository extends JpaRepository<TenantQuotaUsageEntity, String> {

    Optional<TenantQuotaUsageEntity> findByTenantIdAndPeriodKey(String tenantId, String periodKey);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query(
            "SELECT u FROM TenantQuotaUsageEntity u WHERE u.tenantId = :tenantId AND u.periodKey = :periodKey")
    Optional<TenantQuotaUsageEntity> findByTenantIdAndPeriodKeyForUpdate(
            @Param("tenantId") String tenantId, @Param("periodKey") String periodKey);
}
