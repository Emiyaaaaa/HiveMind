package io.agentflow.api.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import io.agentflow.api.config.AgentflowProperties;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.jwt.JwtDecoder;

/**
 * Unit tests for OIDC claim-to-principal translation.
 *
 * <p>Cryptographic verification is delegated to Spring Security's Nimbus
 * decoder. These tests focus on application-owned authorization semantics:
 * tenant isolation, RBAC mapping, and fail-closed required identity claims.
 */
class OidcTokenAuthenticatorTest {

    @Test
    void mapsTenantSubjectAndExplicitRoleMapping() {
        AgentflowProperties.Oidc oidc = baseOidc();
        AgentflowProperties.OidcRoleMapping mapping = new AgentflowProperties.OidcRoleMapping();
        mapping.setClaimValue("platform-admins");
        mapping.setRole("admin");
        oidc.setRoleMappings(List.of(mapping));

        AuthPrincipal principal =
                OidcTokenAuthenticator.toPrincipal(
                        jwt(Map.of("tenant_id", "acme", "roles", List.of("platform-admins"))), oidc);

        assertThat(principal.tenantId()).isEqualTo("acme");
        assertThat(principal.subject()).isEqualTo("user-123");
        assertThat(principal.role()).isEqualTo(Role.ADMIN);
    }

    @Test
    void choosesStrongestRoleAcrossClaimValues() {
        AgentflowProperties.Oidc oidc = baseOidc();

        AuthPrincipal principal =
                OidcTokenAuthenticator.toPrincipal(
                        jwt(Map.of("tenant_id", "acme", "roles", List.of("viewer", "operator"))), oidc);

        assertThat(principal.role()).isEqualTo(Role.OPERATOR);
    }

    @Test
    void acceptsSpaceDelimitedRoleClaims() {
        AgentflowProperties.Oidc oidc = baseOidc();

        AuthPrincipal principal =
                OidcTokenAuthenticator.toPrincipal(
                        jwt(Map.of("tenant_id", "acme", "roles", "viewer admin")), oidc);

        assertThat(principal.role()).isEqualTo(Role.ADMIN);
    }

    @Test
    void fallsBackToConfiguredLeastPrivilegeRoleForUnknownGroups() {
        AgentflowProperties.Oidc oidc = baseOidc();
        oidc.setDefaultRole("viewer");

        AuthPrincipal principal =
                OidcTokenAuthenticator.toPrincipal(
                        jwt(Map.of("tenant_id", "acme", "roles", List.of("billing-team"))), oidc);

        assertThat(principal.role()).isEqualTo(Role.VIEWER);
    }

    @Test
    void rejectsTokenWithoutTenantClaim() {
        AgentflowProperties.Oidc oidc = baseOidc();

        assertThatThrownBy(() -> OidcTokenAuthenticator.toPrincipal(jwt(Map.of("roles", "admin")), oidc))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("tenant claim");
    }

    @Test
    void rejectsTokenWithoutSubject() {
        AgentflowProperties.Oidc oidc = baseOidc();
        Jwt jwt =
                Jwt.withTokenValue("test-token")
                        .header("alg", "none")
                        .claim("tenant_id", "acme")
                        .issuedAt(Instant.parse("2026-01-01T00:00:00Z"))
                        .expiresAt(Instant.parse("2026-01-01T01:00:00Z"))
                        .build();

        assertThatThrownBy(() -> OidcTokenAuthenticator.toPrincipal(jwt, oidc))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("subject");
    }

    @Test
    void disabledOidcDoesNotAttemptTokenDecoding() {
        AgentflowProperties.Auth auth = new AgentflowProperties.Auth();
        auth.getOidc().setEnabled(false);
        JwtDecoder failIfCalled = token -> {
            throw new AssertionError("disabled OIDC must not decode tokens");
        };

        assertThat(new OidcTokenAuthenticator(auth, failIfCalled).authenticate("anything")).isNull();
    }

    @Test
    void invalidDecoderResultIsExposedAsUnauthenticated() {
        AgentflowProperties.Auth auth = new AgentflowProperties.Auth();
        auth.getOidc().setEnabled(true);
        JwtDecoder invalid = token -> {
            throw new org.springframework.security.oauth2.jwt.BadJwtException("invalid signature");
        };

        assertThat(new OidcTokenAuthenticator(auth, invalid).authenticate("bad-token")).isNull();
    }

    private static AgentflowProperties.Oidc baseOidc() {
        AgentflowProperties.Oidc oidc = new AgentflowProperties.Oidc();
        oidc.setTenantClaim("tenant_id");
        oidc.setRoleClaim("roles");
        oidc.setDefaultRole("viewer");
        return oidc;
    }

    private static Jwt jwt(Map<String, Object> claims) {
        Jwt.Builder builder =
                Jwt.withTokenValue("test-token")
                        .header("alg", "none")
                        .subject("user-123")
                        .issuedAt(Instant.parse("2026-01-01T00:00:00Z"))
                        .expiresAt(Instant.parse("2026-01-01T01:00:00Z"));
        claims.forEach(builder::claim);
        return builder.build();
    }
}
