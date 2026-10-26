# OIDC authentication

The Java API can authenticate either a configured API key or an OpenID Connect
access token. OIDC support is implemented as a resource server: users sign in
with the identity provider, and the client sends the provider-issued JWT to the
API. The service does not store browser sessions, user passwords, refresh
tokens, or an OIDC client secret.

## Enabling OIDC

OIDC is deliberately disabled by default. Enable both the existing request
authentication switch and the OIDC switch in the API environment:

```bash
export AGENTFLOW_AUTH_ENABLED=true
export AGENTFLOW_OIDC_ENABLED=true
export AGENTFLOW_OIDC_ISSUER_URI=https://login.example.com/realms/agentflow
export AGENTFLOW_OIDC_AUDIENCE=agentflow-api
```

At startup or on the first OIDC request, the service discovers the issuer's
OpenID Connect metadata and signing keys. In private-network deployments,
configure the JWKS URL explicitly to avoid relying on discovery:

```bash
export AGENTFLOW_OIDC_JWK_SET_URI=https://login.example.com/realms/agentflow/protocol/openid-connect/certs
```

The issuer value remains mandatory even when a JWKS URL is configured. It
prevents accepting a correctly signed token minted for a different issuer.

## Request behaviour

Send an access token with the ordinary Bearer header:

```bash
curl -H "Authorization: Bearer $ACCESS_TOKEN" http://localhost:8080/v1/agents
```

The authentication order is predictable:

1. `X-Api-Key` is treated only as an API key.
2. A Bearer value matching a configured API key remains supported for backward compatibility.
3. Any other Bearer value is validated as an OIDC JWT when OIDC is enabled.

Malformed, expired, wrongly signed, wrong-issuer, or wrong-audience tokens
all receive the same `401` response. This intentionally avoids revealing why
a credential failed validation. Health and actuator endpoints remain open as
they were before authentication was added.

## Tenant mapping

Every accepted OIDC token must have a non-empty tenant claim. The default claim
name is `tenant_id`; configure another claim for providers that use `org_id`,
`tenant`, or a namespaced custom claim:

```bash
export AGENTFLOW_OIDC_TENANT_CLAIM=org_id
```

The claim becomes `AuthPrincipal.tenantId`, so the existing repositories and
services continue filtering reads and writes by tenant. A token missing this
claim is rejected rather than being silently assigned to the default tenant.

## RBAC mapping

By default the service reads a `roles` claim. It accepts a JSON string array,
or a space/comma-delimited string. Values equal to `viewer`, `operator`, or
`admin` map directly to the existing application roles. When several roles are
present, the strongest role wins.

Most identity providers use group names instead. Configure group-to-role
mappings under `agentflow.auth.oidc.role-mappings`:

```yaml
agentflow:
  auth:
    enabled: true
    oidc:
      enabled: true
      issuer-uri: https://login.example.com/realms/agentflow
      audience: agentflow-api
      tenant-claim: org_id
      role-claim: groups
      default-role: viewer
      role-mappings:
        - claim-value: agentflow-admins
          role: admin
        - claim-value: agentflow-operators
          role: operator
```

An unknown group receives `default-role`, which should normally remain
`viewer`. Set `default-role` only to one of the application's existing roles;
configuration with an invalid role fails closed for that request.

## Operational notes

Use HTTPS between clients, the API, and the identity provider. Keep clocks
synchronized, because expiration and not-before checks depend on the server
clock. The JWT decoder uses the provider's JWKS and supports signing-key
rotation; do not pin a static public key in application configuration. API keys
remain a useful migration path, but production clients should move to short-
lived OIDC access tokens and rotate any remaining API keys regularly.
