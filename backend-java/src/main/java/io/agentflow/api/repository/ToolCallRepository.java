package io.agentflow.api.repository;

import io.agentflow.api.entity.ToolCallEntity;
import java.util.Collection;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ToolCallRepository extends JpaRepository<ToolCallEntity, String> {

    List<ToolCallEntity> findAllByStepIdInOrderByCreatedAtAsc(Collection<String> stepIds);
}
