package io.agentflow.api.repository;

import io.agentflow.api.entity.ThreadEntity;
import java.util.List;
import java.util.Optional;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface ThreadRepository extends JpaRepository<ThreadEntity, String> {

    Optional<ThreadEntity> findByIdAndTenantId(String id, String tenantId);

    @Query(
            "SELECT t FROM ThreadEntity t WHERE t.tenantId = :tenantId ORDER BY t.createdAt DESC")
    List<ThreadEntity> findRecentByTenantId(
            @Param("tenantId") String tenantId, Pageable pageable);
}
