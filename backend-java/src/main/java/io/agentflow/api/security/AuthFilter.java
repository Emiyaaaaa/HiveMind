package io.agentflow.api.security;

import io.agentflow.api.config.AgentflowProperties;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * Resolves the caller's tenant + role from an API key or an OIDC Bearer token.
 *
 * <p>When {@code agentflow.auth.enabled=false} (default), every request is
 * treated as {@code admin} on the {@code default} tenant so local development
 * stays unchanged.
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 20)
public class AuthFilter extends OncePerRequestFilter {

    private final AgentflowProperties properties;
    private final OidcTokenAuthenticator oidc;

    public AuthFilter(AgentflowProperties properties) {
        this.properties = properties;
        this.oidc = new OidcTokenAuthenticator(properties.getAuth());
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        String path = request.getRequestURI();
        return path.equals("/")
                || path.equals("/v1/health")
                || path.startsWith("/actuator");
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
            throws ServletException, IOException {
        try {
            AuthPrincipal principal = resolve(request);
            if (principal == null) {
                writeError(response, HttpStatus.UNAUTHORIZED, "Missing or invalid credentials");
                return;
            }
            TenantContext.set(principal);
            filterChain.doFilter(request, response);
        } finally {
            TenantContext.clear();
        }
    }

    private AuthPrincipal resolve(HttpServletRequest request) {
        AgentflowProperties.Auth auth = properties.getAuth();
        if (!auth.isEnabled()) {
            return new AuthPrincipal(
                    TenantContext.DEFAULT_TENANT_ID, Role.ADMIN, "anonymous");
        }
        String apiKey = extractApiKey(request);
        if (apiKey != null) {
            return indexKeys(auth.getKeys()).get(apiKey);
        }
        String bearerToken = extractBearerToken(request);
        if (bearerToken == null) {
            return null;
        }
        AuthPrincipal apiKeyPrincipal = indexKeys(auth.getKeys()).get(bearerToken);
        if (apiKeyPrincipal != null) {
            return apiKeyPrincipal;
        }
        return oidc.authenticate(bearerToken);
    }

    private static String extractApiKey(HttpServletRequest request) {
        String apiKey = request.getHeader("X-Api-Key");
        if (apiKey != null && !apiKey.isBlank()) {
            return apiKey.trim();
        }
        return null;
    }

    private static String extractBearerToken(HttpServletRequest request) {
        String authorization = request.getHeader("Authorization");
        if (authorization == null || authorization.isBlank()) {
            return null;
        }
        String[] parts = authorization.trim().split("\\s+", 2);
        if (parts.length == 2 && "bearer".equalsIgnoreCase(parts[0])) {
            return parts[1].trim();
        }
        return null;
    }

    private static Map<String, AuthPrincipal> indexKeys(
            List<AgentflowProperties.ApiKeyEntry> entries) {
        Map<String, AuthPrincipal> map = new LinkedHashMap<>();
        if (entries == null) {
            return map;
        }
        for (AgentflowProperties.ApiKeyEntry entry : entries) {
            if (entry.getKey() == null || entry.getKey().isBlank()) {
                continue;
            }
            String tenant =
                    entry.getTenantId() == null || entry.getTenantId().isBlank()
                            ? TenantContext.DEFAULT_TENANT_ID
                            : entry.getTenantId().trim();
            Role role =
                    entry.getRole() == null || entry.getRole().isBlank()
                            ? Role.VIEWER
                            : Role.parse(entry.getRole());
            String token = entry.getKey().trim();
            map.put(
                    token,
                    new AuthPrincipal(tenant, role, token.substring(0, Math.min(8, token.length()))));
        }
        return map;
    }

    private static void writeError(HttpServletResponse response, HttpStatus status, String detail)
            throws IOException {
        response.setStatus(status.value());
        response.setContentType("application/json");
        response.setCharacterEncoding("UTF-8");
        if (status == HttpStatus.UNAUTHORIZED) {
            response.setHeader("WWW-Authenticate", "Bearer");
        }
        String body =
                "{\"detail\":\""
                        + detail.replace("\\", "\\\\").replace("\"", "\\\"")
                        + "\"}";
        response.getWriter().write(body);
    }
}
