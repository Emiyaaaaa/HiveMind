package io.agentflow.api.repository;

import io.agentflow.api.entity.CheckpointEntity;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface CheckpointRepository extends JpaRepository<CheckpointEntity, String> {

    List<CheckpointEntity> findAllByRunIdOrderByIndexAsc(String runId);

    long deleteByRunId(String runId);

    long deleteByRunIdIn(Iterable<String> runIds);
}
