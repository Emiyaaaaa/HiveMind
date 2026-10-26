package io.agentflow.api.repository;

import io.agentflow.api.entity.AgentQuotaUsageEntity;
import jakarta.persistence.LockModeType;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface AgentQuotaUsageRepository extends JpaRepository<AgentQuotaUsageEntity, String> {

    Optional<AgentQuotaUsageEntity> findByAgentIdAndPeriodKey(String agentId, String periodKey);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query(
            "SELECT u FROM AgentQuotaUsageEntity u WHERE u.agentId = :agentId AND u.periodKey = :periodKey")
    Optional<AgentQuotaUsageEntity> findByAgentIdAndPeriodKeyForUpdate(
            @Param("agentId") String agentId, @Param("periodKey") String periodKey);
}
