package io.agentflow.api.service;

import org.springframework.http.HttpStatus;

public class RegressionExecutionException extends RuntimeException {

    private final HttpStatus status;

    private RegressionExecutionException(HttpStatus status, String message, Throwable cause) {
        super(message, cause);
        this.status = status;
    }

    static RegressionExecutionException invalid(String message) {
        return new RegressionExecutionException(HttpStatus.UNPROCESSABLE_ENTITY, message, null);
    }

    static RegressionExecutionException notFound(String executionId) {
        return new RegressionExecutionException(
                HttpStatus.NOT_FOUND,
                "Regression execution not found or expired: " + executionId,
                null);
    }

    static RegressionExecutionException unavailable(String message, Throwable cause) {
        return new RegressionExecutionException(HttpStatus.SERVICE_UNAVAILABLE, message, cause);
    }

    public HttpStatus status() {
        return status;
    }
}
