package io.agentflow.api.security;

public record AuthPrincipal(String tenantId, Role role, String subject) {}
