package io.agentflow.api.service;

public class AgentNameConflictException extends RuntimeException {
    public AgentNameConflictException(String name) {
        super("Agent name already exists: " + name);
    }
}
