package io.agentflow.api.security;

public final class AccessControl {

    private AccessControl() {}

    public static AuthPrincipal require(Role minimum) {
        AuthPrincipal principal = TenantContext.require();
        if (!principal.role().atLeast(minimum)) {
            throw new ForbiddenException(
                    "Requires role " + minimum.name().toLowerCase() + " or higher");
        }
        return principal;
    }

    public static String tenantId(Role minimum) {
        return require(minimum).tenantId();
    }
}
