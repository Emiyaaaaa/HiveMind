package io.agentflow.api.service;

import org.springframework.http.HttpStatus;

public class ScheduleException extends RuntimeException {

    private final HttpStatus status;

    public ScheduleException(HttpStatus status, String message) {
        super(message);
        this.status = status;
    }

    public static ScheduleException notFound(String id) {
        return new ScheduleException(HttpStatus.NOT_FOUND, "Schedule not found: " + id);
    }

    public HttpStatus status() {
        return status;
    }
}
