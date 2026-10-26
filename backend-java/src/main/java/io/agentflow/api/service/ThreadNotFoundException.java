package io.agentflow.api.service;

public class ThreadNotFoundException extends RuntimeException {

    public ThreadNotFoundException(String threadId) {
        super("Thread not found: " + threadId);
    }
}
