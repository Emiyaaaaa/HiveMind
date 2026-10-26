package io.agentflow.api.dto;

import java.util.List;

public class MessagePageResponse {

    private List<MessageResponse> items;
    private Integer nextCursor;
    private boolean hasMore;

    public static MessagePageResponse of(
            List<MessageResponse> items, Integer nextCursor, boolean hasMore) {
        MessagePageResponse page = new MessagePageResponse();
        page.items = items;
        page.nextCursor = nextCursor;
        page.hasMore = hasMore;
        return page;
    }

    public List<MessageResponse> getItems() {
        return items;
    }

    public Integer getNextCursor() {
        return nextCursor;
    }

    public boolean isHasMore() {
        return hasMore;
    }
}
