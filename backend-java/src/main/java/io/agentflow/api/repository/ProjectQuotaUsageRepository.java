package io.agentflow.api.repository;

import io.agentflow.api.entity.ProjectQuotaUsageEntity;
import jakarta.persistence.LockModeType;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface ProjectQuotaUsageRepository extends JpaRepository<ProjectQuotaUsageEntity, String> {

    Optional<ProjectQuotaUsageEntity> findByProjectIdAndPeriodKey(String projectId, String periodKey);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query(
            "SELECT u FROM ProjectQuotaUsageEntity u WHERE u.projectId = :projectId AND u.periodKey = :periodKey")
    Optional<ProjectQuotaUsageEntity> findByProjectIdAndPeriodKeyForUpdate(
            @Param("projectId") String projectId, @Param("periodKey") String periodKey);
}
