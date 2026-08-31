package io.agentflow.api.security;

import io.agentflow.api.config.AgentflowProperties;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import org.springframework.security.oauth2.core.DelegatingOAuth2TokenValidator;
import org.springframework.security.oauth2.core.OAuth2Error;
import org.springframework.security.oauth2.core.OAuth2TokenValidator;
import org.springframework.security.oauth2.core.OAuth2TokenValidatorResult;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.JwtDecoders;
import org.springframework.security.oauth2.jwt.JwtException;
import org.springframework.security.oauth2.jwt.JwtValidators;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;

/**
 * Verifies an OpenID Connect JWT and translates its claims into the existing
 * application principal used by multi-tenancy and RBAC.
 *
 * <p>This class intentionally implements the resource-server half of OIDC.
 * The browser or API client authenticates with the identity provider, then
 * sends the resulting access token in {@code Authorization: Bearer <token>}.
 * No application session, redirect callback, or client secret is kept by this
 * API, which makes the flow appropriate for both the web UI and automation.
 *
 * <p>The decoder validates JWT signature, expiration, not-before, and issuer.
 * If configured, audience is also required. Invalid or incomplete tokens are
 * represented by a {@code null} result so the filter can return one generic
 * 401 response without leaking validation details to callers.
 */
public final class OidcTokenAuthenticator {

    private static final OAuth2Error INVALID_AUDIENCE =
            new OAuth2Error("invalid_token", "Token audience is not accepted", null);

    private final AgentflowProperties.Auth auth;
    private volatile JwtDecoder decoder;

    public OidcTokenAuthenticator(AgentflowProperties.Auth auth) {
        this(auth, null);
    }

    OidcTokenAuthenticator(AgentflowProperties.Auth auth, JwtDecoder decoder) {
        this.auth = auth;
        this.decoder = decoder;
    }

    /**
     * Returns a principal for a valid configured OIDC token, otherwise null.
     *
     * <p>Returning null lets {@link AuthFilter} preserve the same behaviour
     * for an unknown API key and an invalid OIDC token.
     */
    public AuthPrincipal authenticate(String token) {
        AgentflowProperties.Oidc oidc = auth.getOidc();
        if (!oidc.isEnabled() || token == null || token.isBlank()) {
            return null;
        }
        try {
            return toPrincipal(decoder().decode(token), oidc);
        } catch (JwtException | IllegalArgumentException ex) {
            return null;
        }
    }

    private JwtDecoder decoder() {
        JwtDecoder current = decoder;
        if (current != null) {
            return current;
        }
        synchronized (this) {
            if (decoder == null) {
                decoder = createDecoder(auth.getOidc());
            }
            return decoder;
        }
    }

    private static JwtDecoder createDecoder(AgentflowProperties.Oidc oidc) {
        String issuer = requireText(oidc.getIssuerUri(), "agentflow.auth.oidc.issuer-uri");
        JwtDecoder result;
        if (hasText(oidc.getJwkSetUri())) {
            NimbusJwtDecoder nimbus = NimbusJwtDecoder.withJwkSetUri(oidc.getJwkSetUri().trim()).build();
            nimbus.setJwtValidator(validators(issuer, oidc.getAudience()));
            result = nimbus;
        } else {
            // Spring obtains discovery metadata and JWKS from the verified issuer.
            result = JwtDecoders.fromIssuerLocation(issuer);
            if (result instanceof NimbusJwtDecoder nimbus) {
                nimbus.setJwtValidator(validators(issuer, oidc.getAudience()));
            }
        }
        return result;
    }

    private static OAuth2TokenValidator<Jwt> validators(String issuer, String audience) {
        OAuth2TokenValidator<Jwt> issuerValidator = JwtValidators.createDefaultWithIssuer(issuer);
        if (!hasText(audience)) {
            return issuerValidator;
        }
        String expectedAudience = audience.trim();
        OAuth2TokenValidator<Jwt> audienceValidator =
                jwt ->
                        jwt.getAudience().contains(expectedAudience)
                                ? OAuth2TokenValidatorResult.success()
                                : OAuth2TokenValidatorResult.failure(INVALID_AUDIENCE);
        return new DelegatingOAuth2TokenValidator<>(issuerValidator, audienceValidator);
    }

    /** Resolves the required tenant claim and the strongest mapped application role. */
    static AuthPrincipal toPrincipal(Jwt jwt, AgentflowProperties.Oidc oidc) {
        String tenantClaim = requireText(oidc.getTenantClaim(), "agentflow.auth.oidc.tenant-claim");
        String tenantId = stringClaim(jwt, tenantClaim);
        if (!hasText(tenantId)) {
            throw new IllegalArgumentException("OIDC token is missing its tenant claim");
        }

        String subject = jwt.getSubject();
        if (!hasText(subject)) {
            throw new IllegalArgumentException("OIDC token is missing its subject");
        }
        return new AuthPrincipal(tenantId.trim(), resolveRole(jwt, oidc), subject.trim());
    }

    private static Role resolveRole(Jwt jwt, AgentflowProperties.Oidc oidc) {
        Role resolved = Role.parse(requireText(oidc.getDefaultRole(), "agentflow.auth.oidc.default-role"));
        for (String claimValue : claimValues(jwt.getClaim(oidc.getRoleClaim()))) {
            Role mapped = mappedRole(claimValue, oidc.getRoleMappings());
            if (mapped == null) {
                mapped = parseRoleOrNull(claimValue);
            }
            if (mapped != null && mapped.atLeast(resolved)) {
                resolved = mapped;
            }
        }
        return resolved;
    }

    private static Role mappedRole(
            String claimValue, List<AgentflowProperties.OidcRoleMapping> mappings) {
        if (mappings == null) {
            return null;
        }
        for (AgentflowProperties.OidcRoleMapping mapping : mappings) {
            if (mapping == null || !hasText(mapping.getClaimValue())) {
                continue;
            }
            if (mapping.getClaimValue().trim().equalsIgnoreCase(claimValue)) {
                return Role.parse(requireText(mapping.getRole(), "OIDC role mapping role"));
            }
        }
        return null;
    }

    private static List<String> claimValues(Object claim) {
        List<String> values = new ArrayList<>();
        if (claim instanceof String value) {
            for (String piece : value.split("[ ,]+")) {
                if (hasText(piece)) {
                    values.add(piece.trim());
                }
            }
        } else if (claim instanceof Collection<?> collection) {
            for (Object value : collection) {
                if (value != null && hasText(value.toString())) {
                    values.add(value.toString().trim());
                }
            }
        }
        return values;
    }

    private static String stringClaim(Jwt jwt, String name) {
        Object value = jwt.getClaim(name);
        return value == null ? null : value.toString();
    }

    private static Role parseRoleOrNull(String value) {
        try {
            return Role.parse(value);
        } catch (IllegalArgumentException ex) {
            return null;
        }
    }

    private static String requireText(String value, String property) {
        if (!hasText(value)) {
            throw new IllegalArgumentException(property + " must be configured");
        }
        return value.trim();
    }

    private static boolean hasText(String value) {
        return value != null && !value.isBlank();
    }
}
