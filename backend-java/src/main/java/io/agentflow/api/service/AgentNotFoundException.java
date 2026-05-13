package io.agentflow.api.service;

public class AgentNotFoundException extends RuntimeException {
    public AgentNotFoundException(String id) {
        super("Agent not found: " + id);
    }
}
