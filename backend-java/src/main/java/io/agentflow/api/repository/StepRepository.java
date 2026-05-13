package io.agentflow.api.repository;

import io.agentflow.api.entity.StepEntity;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface StepRepository extends JpaRepository<StepEntity, String> {

    List<StepEntity> findAllByRunIdOrderByIndexAsc(String runId);
}
