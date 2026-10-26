package io.agentflow.api.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

class AccessControlTest {

    @AfterEach
    void clear() {
        TenantContext.clear();
    }

    @Test
    void adminSatisfiesViewer() {
        TenantContext.set(new AuthPrincipal("t1", Role.ADMIN, "x"));
        assertThat(AccessControl.tenantId(Role.VIEWER)).isEqualTo("t1");
    }

    @Test
    void viewerDeniedAdmin() {
        TenantContext.set(new AuthPrincipal("t1", Role.VIEWER, "x"));
        assertThatThrownBy(() -> AccessControl.require(Role.ADMIN))
                .isInstanceOf(ForbiddenException.class);
    }

    @Test
    void missingPrincipalIsUnauthorized() {
        assertThatThrownBy(() -> AccessControl.require(Role.VIEWER))
                .isInstanceOf(UnauthorizedException.class);
    }
}
