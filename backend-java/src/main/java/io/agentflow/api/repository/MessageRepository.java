package io.agentflow.api.repository;

import io.agentflow.api.entity.MessageEntity;
import java.time.Instant;
import java.util.List;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface MessageRepository extends JpaRepository<MessageEntity, String> {

    List<MessageEntity> findAllByRunIdOrderByIndexAsc(String runId);

    List<MessageEntity> findByRunIdOrderByIndexDesc(String runId, Pageable pageable);

    List<MessageEntity> findByRunIdAndIndexLessThanOrderByIndexDesc(
            String runId, int index, Pageable pageable);

    /**
     * Thread transcript rows as {@code [MessageEntity, RunEntity]} ordered
     * newest-first for limit-based paging.
     */
    @Query(
            """
            SELECT m, r FROM MessageEntity m, RunEntity r
            WHERE m.runId = r.id AND r.threadId = :threadId
            ORDER BY r.createdAt DESC, m.index DESC, m.id DESC
            """)
    List<Object[]> findThreadMessagesNewestFirst(
            @Param("threadId") String threadId, Pageable pageable);

    /**
     * Messages older than the opaque cursor {@code (runCreatedAt, index, id)},
     * still newest-first within that older window.
     */
    @Query(
            """
            SELECT m, r FROM MessageEntity m, RunEntity r
            WHERE m.runId = r.id AND r.threadId = :threadId
              AND (
                    r.createdAt < :cursorCreated
                 OR (r.createdAt = :cursorCreated AND m.index < :cursorIndex)
                 OR (r.createdAt = :cursorCreated AND m.index = :cursorIndex
                     AND m.id < :cursorId)
              )
            ORDER BY r.createdAt DESC, m.index DESC, m.id DESC
            """)
    List<Object[]> findThreadMessagesOlderThan(
            @Param("threadId") String threadId,
            @Param("cursorCreated") Instant cursorCreated,
            @Param("cursorIndex") int cursorIndex,
            @Param("cursorId") String cursorId,
            Pageable pageable);

    long deleteByRunId(String runId);

    long deleteByRunIdIn(Iterable<String> runIds);
}
