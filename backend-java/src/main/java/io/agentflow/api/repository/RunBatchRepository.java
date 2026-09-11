package io.agentflow.api.repository;

import io.agentflow.api.entity.RunBatchEntity;
import java.util.List;
import java.util.Optional;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface RunBatchRepository extends JpaRepository<RunBatchEntity, String> {

    Optional<RunBatchEntity> findByIdAndTenantId(String id, String tenantId);

    @Query(
            "SELECT b FROM RunBatchEntity b WHERE b.tenantId = :tenantId ORDER BY b.createdAt DESC")
    List<RunBatchEntity> findRecentByTenantId(
            @Param("tenantId") String tenantId, Pageable pageable);
}
