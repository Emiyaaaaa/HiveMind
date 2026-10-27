package io.agentflow.api.repository;

import io.agentflow.api.entity.ProjectQuotaConfigEntity;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ProjectQuotaConfigRepository extends JpaRepository<ProjectQuotaConfigEntity, String> {

    Optional<ProjectQuotaConfigEntity> findByProjectId(String projectId);
}
