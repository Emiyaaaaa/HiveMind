package io.agentflow.api.security;

/** Request-scoped auth identity. Cleared by {@link AuthFilter} after each request. */
public final class TenantContext {

    public static final String DEFAULT_TENANT_ID = "default";

    private static final ThreadLocal<AuthPrincipal> CURRENT = new ThreadLocal<>();

    private TenantContext() {}

    public static void set(AuthPrincipal principal) {
        CURRENT.set(principal);
    }

    public static AuthPrincipal get() {
        return CURRENT.get();
    }

    public static AuthPrincipal require() {
        AuthPrincipal principal = CURRENT.get();
        if (principal == null) {
            throw new UnauthorizedException("Authentication required");
        }
        return principal;
    }

    public static String tenantId() {
        return require().tenantId();
    }

    public static void clear() {
        CURRENT.remove();
    }
}
