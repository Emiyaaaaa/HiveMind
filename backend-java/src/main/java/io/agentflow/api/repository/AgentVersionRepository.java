package io.agentflow.api.repository;

import io.agentflow.api.entity.AgentVersionEntity;
import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

public interface AgentVersionRepository extends JpaRepository<AgentVersionEntity, String> {

    List<AgentVersionEntity> findByAgentIdOrderByVersionDesc(String agentId);

    Optional<AgentVersionEntity> findByAgentIdAndVersion(String agentId, int version);
}
