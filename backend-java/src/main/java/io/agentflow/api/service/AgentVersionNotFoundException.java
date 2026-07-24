package io.agentflow.api.service;

public class AgentVersionNotFoundException extends RuntimeException {

    public AgentVersionNotFoundException(String agentId, int version) {
        super("Agent version not found: " + agentId + "@v" + version);
    }

    public AgentVersionNotFoundException(int version) {
        super("Agent version not found: " + version);
    }
}
