package io.agentflow.api.service;

public class AttachmentTooLargeException extends RuntimeException {

    private final long size;
    private final long limit;

    public AttachmentTooLargeException(long size, long limit) {
        super("attachment " + size + " bytes exceeds limit " + limit);
        this.size = size;
        this.limit = limit;
    }

    public long getSize() {
        return size;
    }

    public long getLimit() {
        return limit;
    }
}
