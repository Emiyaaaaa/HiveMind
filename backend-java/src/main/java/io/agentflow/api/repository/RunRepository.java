package io.agentflow.api.repository;

import io.agentflow.api.entity.RunEntity;
import java.util.List;
import java.util.Optional;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface RunRepository extends JpaRepository<RunEntity, String> {

    @Query(
            "SELECT r FROM RunEntity r WHERE r.tenantId = :tenantId ORDER BY r.createdAt DESC")
    List<RunEntity> findRecentByTenantId(
            @Param("tenantId") String tenantId, Pageable pageable);

    Optional<RunEntity> findByIdAndTenantId(String id, String tenantId);

    List<RunEntity> findAllByTenantId(String tenantId);
}
