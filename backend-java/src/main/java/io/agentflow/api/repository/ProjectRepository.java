package io.agentflow.api.repository;

import io.agentflow.api.entity.ProjectEntity;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ProjectRepository extends JpaRepository<ProjectEntity, String> {

    Optional<ProjectEntity> findByIdAndTenantId(String id, String tenantId);
}
