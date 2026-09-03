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
import java.util.ArrayList;
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
        thread.setProjectId(req.getProjectId());
        thread.setUserId(req.getUserId());
        thread.setTitle(req.getTitle());
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
        int capped = Math.max(1, Math.min(limit, 200));
        List<RunEntity> threadRuns = runs.findAllByThreadIdOrderByCreatedAtAsc(thread.getId());
        List<ThreadMessageResponse> all = new ArrayList<>();
        for (RunEntity run : threadRuns) {
            for (MessageEntity message : messages.findAllByRunIdOrderByIndexAsc(run.getId())) {
                all.add(ThreadMessageResponse.from(message, run.getId()));
            }
        }
        if (cursor != null && !cursor.isBlank()) {
            all = all.stream().filter(m -> cursorKey(m).compareTo(cursor) < 0).toList();
        }
        boolean hasMore = all.size() > capped;
        List<ThreadMessageResponse> page =
                hasMore ? all.subList(Math.max(0, all.size() - capped), all.size()) : all;
        String nextCursor = hasMore && !page.isEmpty() ? cursorKey(page.get(0)) : null;
        return new ThreadMessageResponse.Page(List.copyOf(page), nextCursor, hasMore);
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

    private static String cursorKey(ThreadMessageResponse message) {
        return message.getCreatedAt()
                + "|"
                + String.format("%08d", message.getIndex())
                + "|"
                + message.getId();
    }
}
