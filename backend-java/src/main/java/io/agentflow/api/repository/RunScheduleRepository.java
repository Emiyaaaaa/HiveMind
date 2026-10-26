package io.agentflow.api.repository;

import io.agentflow.api.entity.RunScheduleEntity;
import java.util.List;
import java.util.Optional;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface RunScheduleRepository extends JpaRepository<RunScheduleEntity, String> {

    Optional<RunScheduleEntity> findByIdAndTenantId(String id, String tenantId);

    @Query(
            "SELECT s FROM RunScheduleEntity s WHERE s.tenantId = :tenantId ORDER BY s.createdAt DESC")
    List<RunScheduleEntity> findRecentByTenantId(
            @Param("tenantId") String tenantId, Pageable pageable);
}
