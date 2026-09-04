package io.agentflow.api.repository;

import io.agentflow.api.entity.AttachmentEntity;
import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

public interface AttachmentRepository extends JpaRepository<AttachmentEntity, String> {

    Optional<AttachmentEntity> findByIdAndTenantId(String id, String tenantId);

    List<AttachmentEntity> findByRunIdAndTenantIdOrderByCreatedAtAsc(String runId, String tenantId);

    List<AttachmentEntity> findByRunId(String runId);

    List<AttachmentEntity> findByTenantId(String tenantId);

    long deleteByRunId(String runId);

    long deleteByTenantId(String tenantId);
}
