package io.agentflow.api.service;

import io.agentflow.api.dto.RunResponse;
import io.agentflow.api.dto.ThreadCreateRequest;
import io.agentflow.api.dto.ThreadMessageResponse;
import io.agentflow.api.dto.ThreadResponse;
import io.agentflow.api.entity.AgentEntity;
import io.agentflow.api.entity.MessageEntity;
import io.agentflow.api.entity.RunEntity;
import io.agentflow.api.entity.ThreadEntity;
import io.agentflow.api.repository.MessageRepository;
import io.agentflow.api.repository.RunRepository;
import io.agentflow.api.repository.ThreadRepository;
import io.agentflow.api.security.AccessControl;
import io.agentflow.api.security.Role;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class ThreadService {

    private final ThreadRepository threads;
    private final RunRepository runs;
    private final MessageRepository messages;
    private final AgentService agentService;

    public ThreadService(
            ThreadRepository threads,
            RunRepository runs,
            MessageRepository messages,
            AgentService agentService) {
        this.threads = threads;
        this.runs = runs;
        this.messages = messages;
        this.agentService = agentService;
    }

    @Transactional
    public ThreadResponse create(ThreadCreateRequest req) {
        AccessControl.require(Role.OPERATOR);
        AgentEntity agent = agentService.getEntity(req.getAgentId());
        ThreadEntity thread = new ThreadEntity();
        thread.setTenantId(agent.getTenantId());
        thread.setAgentId(agent.getId());
        // Prefer explicit project_id; otherwise leave null (Java AgentEntity
        // does not yet mirror agents.project_id — Python create inherits it).
        thread.setProjectId(blankToNull(req.getProjectId()));
        thread.setUserId(blankToNull(req.getUserId()));
        thread.setTitle(blankToNull(req.getTitle()));
        return ThreadResponse.fromEntity(threads.save(thread));
    }

    @Transactional(readOnly = true)
    public List<ThreadResponse> list(int limit) {
        String tenantId = AccessControl.tenantId(Role.VIEWER);
        int capped = Math.max(1, Math.min(limit, 200));
        return threads.findRecentByTenantId(tenantId, PageRequest.of(0, capped)).stream()
                .map(ThreadResponse::fromEntity)
                .toList();
    }

    @Transactional(readOnly = true)
    public ThreadResponse get(String id) {
        return ThreadResponse.fromEntity(requireThread(id));
    }

    @Transactional(readOnly = true)
    public ThreadMessageResponse.Page listMessages(String id, String cursor, int limit) {
        ThreadEntity thread = requireThread(id);
        int capped = Math.max(1, Math.min(limit, MessagePagination.PAGE_MAX));
        PageRequest page = PageRequest.of(0, capped + 1);

        List<Object[]> rows;
        CursorParts parsed = parseCursor(cursor);
        if (parsed != null) {
            rows =
                    messages.findThreadMessagesOlderThan(
                            thread.getId(),
                            parsed.createdAt(),
                            parsed.index(),
                            parsed.id(),
                            page);
        } else {
            rows = messages.findThreadMessagesNewestFirst(thread.getId(), page);
        }

        List<ThreadMessageResponse> newestFirst = new ArrayList<>(rows.size());
        for (Object[] row : rows) {
            MessageEntity message = (MessageEntity) row[0];
            RunEntity run = (RunEntity) row[1];
            newestFirst.add(
                    ThreadMessageResponse.from(message, run.getId(), run.getCreatedAt()));
        }

        boolean hasMore = newestFirst.size() > capped;
        List<ThreadMessageResponse> pageDesc =
                hasMore ? newestFirst.subList(0, capped) : newestFirst;
        List<ThreadMessageResponse> ascending = new ArrayList<>(pageDesc);
        Collections.reverse(ascending);
        String nextCursor =
                hasMore && !ascending.isEmpty() ? cursorKey(ascending.get(0)) : null;
        return new ThreadMessageResponse.Page(List.copyOf(ascending), nextCursor, hasMore);
    }

    @Transactional(readOnly = true)
    public List<RunResponse> listRuns(String id, int limit) {
        ThreadEntity thread = requireThread(id);
        int capped = Math.max(1, Math.min(limit, 200));
        return runs.findAllByThreadIdOrderByCreatedAtAsc(thread.getId()).stream()
                .limit(capped)
                .map(RunResponse::fromEntity)
                .toList();
    }

    ThreadEntity requireThread(String id) {
        String tenantId = AccessControl.tenantId(Role.VIEWER);
        return threads
                .findByIdAndTenantId(id, tenantId)
                .orElseThrow(() -> new ThreadNotFoundException(id));
    }

    /**
     * Cursor uses the run's created_at (sort key) plus message index/id so
     * pagination matches transcript order across runs.
     */
    private static String cursorKey(ThreadMessageResponse message) {
        Instant sortAt =
                message.getRunCreatedAt() != null
                        ? message.getRunCreatedAt()
                        : message.getCreatedAt();
        return sortAt
                + "|"
                + String.format("%08d", message.getIndex())
                + "|"
                + message.getId();
    }

    private static CursorParts parseCursor(String cursor) {
        if (cursor == null || cursor.isBlank()) {
            return null;
        }
        String[] parts = cursor.split("\\|", 3);
        if (parts.length != 3) {
            return null;
        }
        try {
            return new CursorParts(Instant.parse(parts[0]), Integer.parseInt(parts[1]), parts[2]);
        } catch (RuntimeException ex) {
            return null;
        }
    }

    private static String blankToNull(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        return value;
    }

    private record CursorParts(Instant createdAt, int index, String id) {}
}
