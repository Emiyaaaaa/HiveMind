package io.agentflow.api.repository;

import io.agentflow.api.entity.MessageEntity;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface MessageRepository extends JpaRepository<MessageEntity, String> {

    List<MessageEntity> findAllByRunIdOrderByIndexAsc(String runId);
}
