package io.agentflow.api.security;

/**
 * Coarse RBAC roles. Higher ordinals include lower privileges.
 *
 * <ul>
 *   <li>{@link #VIEWER} — list/get agents, runs, SSE</li>
 *   <li>{@link #OPERATOR} — create/cancel/retry/resume runs</li>
 *   <li>{@link #ADMIN} — create/update/restore agents</li>
 * </ul>
 */
public enum Role {
    VIEWER,
    OPERATOR,
    ADMIN;

    public boolean atLeast(Role required) {
        return this.ordinal() >= required.ordinal();
    }

    public static Role parse(String raw) {
        return Role.valueOf(raw.trim().toUpperCase());
    }
}
