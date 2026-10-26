package io.agentflow.api.repository;

import io.agentflow.api.entity.RunAuditEventEntity;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface RunAuditEventRepository extends JpaRepository<RunAuditEventEntity, String> {

    List<RunAuditEventEntity> findAllByRunIdAndTenantIdOrderByCreatedAtAscIdAsc(
            String runId, String tenantId);
}
