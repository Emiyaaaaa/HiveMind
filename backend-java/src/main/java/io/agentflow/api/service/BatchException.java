package io.agentflow.api.service;

import org.springframework.http.HttpStatus;

public class BatchException extends RuntimeException {

    private final HttpStatus status;

    public BatchException(HttpStatus status, String message) {
        super(message);
        this.status = status;
    }

    public static BatchException notFound(String id) {
        return new BatchException(HttpStatus.NOT_FOUND, "Batch not found: " + id);
    }

    public static BatchException invalid(String message) {
        return new BatchException(HttpStatus.UNPROCESSABLE_ENTITY, message);
    }

    public HttpStatus status() {
        return status;
    }
}
