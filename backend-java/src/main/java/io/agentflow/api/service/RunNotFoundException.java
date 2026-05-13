package io.agentflow.api.service;

public class RunNotFoundException extends RuntimeException {
    public RunNotFoundException(String id) {
        super("Run not found: " + id);
    }
}
