package io.agentflow.api.repository;

import io.agentflow.api.entity.MessageEntity;
import java.util.List;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

public interface MessageRepository extends JpaRepository<MessageEntity, String> {

    List<MessageEntity> findAllByRunIdOrderByIndexAsc(String runId);

    List<MessageEntity> findByRunIdOrderByIndexDesc(String runId, Pageable pageable);

    List<MessageEntity> findByRunIdAndIndexLessThanOrderByIndexDesc(
            String runId, int index, Pageable pageable);

    long deleteByRunId(String runId);

    long deleteByRunIdIn(Iterable<String> runIds);
}
