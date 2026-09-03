package io.agentflow.api.dto;

import io.agentflow.api.entity.MessageEntity;
import java.time.Instant;
import java.util.List;
import java.util.Map;

public class ThreadMessageResponse {

    private String id;
    private String runId;
    private int index;
    private String stepId;
    private String role;
    private String name;
    private String content;
    private String toolCallId;
    private Map<String, Object> extra;
    private Instant createdAt;

    public static ThreadMessageResponse from(MessageEntity entity, String runId) {
        ThreadMessageResponse dto = new ThreadMessageResponse();
        dto.id = entity.getId();
        dto.runId = runId;
        dto.index = entity.getIndex();
        dto.stepId = entity.getStepId();
        dto.role = entity.getRole();
        dto.name = entity.getName();
        dto.content = entity.getContent();
        dto.toolCallId = entity.getToolCallId();
        dto.extra = entity.getExtra();
        dto.createdAt = entity.getCreatedAt();
        return dto;
    }

    public String getId() {
        return id;
    }

    public String getRunId() {
        return runId;
    }

    public int getIndex() {
        return index;
    }

    public String getStepId() {
        return stepId;
    }

    public String getRole() {
        return role;
    }

    public String getName() {
        return name;
    }

    public String getContent() {
        return content;
    }

    public String getToolCallId() {
        return toolCallId;
    }

    public Map<String, Object> getExtra() {
        return extra;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public static class Page {
        private final List<ThreadMessageResponse> items;
        private final String nextCursor;
        private final boolean hasMore;

        public Page(List<ThreadMessageResponse> items, String nextCursor, boolean hasMore) {
            this.items = items;
            this.nextCursor = nextCursor;
            this.hasMore = hasMore;
        }

        public List<ThreadMessageResponse> getItems() {
            return items;
        }

        public String getNextCursor() {
            return nextCursor;
        }

        public boolean isHasMore() {
            return hasMore;
        }
    }
}
