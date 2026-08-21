package io.agentflow.api.repository;

import io.agentflow.api.entity.AgentEntity;
import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

public interface AgentRepository extends JpaRepository<AgentEntity, String> {

    List<AgentEntity> findAllByTenantIdOrderByCreatedAtDesc(String tenantId);

    boolean existsByTenantIdAndName(String tenantId, String name);

    Optional<AgentEntity> findByIdAndTenantId(String id, String tenantId);
}
