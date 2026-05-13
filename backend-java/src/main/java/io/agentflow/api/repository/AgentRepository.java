package io.agentflow.api.repository;

import io.agentflow.api.entity.AgentEntity;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface AgentRepository extends JpaRepository<AgentEntity, String> {

    List<AgentEntity> findAllByOrderByCreatedAtDesc();

    boolean existsByName(String name);
}
