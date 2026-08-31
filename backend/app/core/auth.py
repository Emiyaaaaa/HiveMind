"""API-key auth with organization, project, and Agent scoped RBAC.

Auth is off by default so local tests and quickstarts stay open. When
``AGENTFLOW_AUTH_ENABLED=true``, every ``/v1/*`` request except health must
present ``Authorization: Bearer <key>`` or ``X-Api-Key: <key>``. Keys are
configured as ``key:organization:role[:project_id[:agent_id]]`` entries in
``AGENTFLOW_AUTH_API_KEYS``. The three-part legacy form is organization-wide.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from enum import IntEnum
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.core.config import Settings, get_settings
from app.models.agent import DEFAULT_TENANT_ID


class Role(IntEnum):
    VIEWER = 1
    OPERATOR = 2
    ADMIN = 3

    @classmethod
    def parse(cls, value: str) -> Role:
        try:
            return cls[value.strip().upper()]
        except KeyError as exc:
            raise ValueError(f"Unknown role: {value}") from exc


@dataclass(frozen=True, slots=True)
class AuthPrincipal:
    tenant_id: str
    role: Role
    subject: str
    project_id: str | None = None
    agent_id: str | None = None

    def require(self, minimum: Role) -> None:
        if self.role < minimum:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role {minimum.name.lower()} or higher",
            )

    def require_organization(self, organization_id: str, minimum: Role) -> None:
        self._require_organization(organization_id)
        if self.project_id is not None or self.agent_id is not None:
            self._not_found()
        self.require(minimum)

    def require_project(self, organization_id: str, project_id: str, minimum: Role) -> None:
        self._require_organization(organization_id)
        if self.project_id is not None and self.project_id != project_id:
            self._not_found()
        if self.agent_id is not None:
            self._not_found()
        self.require(minimum)

    def require_agent(
        self, organization_id: str, project_id: str | None, agent_id: str, minimum: Role
    ) -> None:
        self._require_organization(organization_id)
        if self.project_id is not None and self.project_id != project_id:
            self._not_found()
        if self.agent_id is not None and self.agent_id != agent_id:
            self._not_found()
        self.require(minimum)

    def _require_organization(self, organization_id: str) -> None:
        if self.tenant_id != organization_id:
            self._not_found()

    @staticmethod
    def _not_found() -> None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")


_principal: ContextVar[AuthPrincipal | None] = ContextVar(
    "auth_principal", default=None
)


def set_principal(principal: AuthPrincipal | None) -> None:
    _principal.set(principal)


def current_principal() -> AuthPrincipal | None:
    return _principal.get()


def parse_api_keys(raw: str) -> dict[str, AuthPrincipal]:
    """Parse scoped API keys, preserving ``key:tenant:role`` compatibility."""
    out: dict[str, AuthPrincipal] = {}
    for chunk in raw.split(","):
        piece = chunk.strip()
        if not piece:
            continue
        parts = piece.split(":")
        if len(parts) not in (3, 4, 5):
            raise ValueError(
                "Invalid auth key entry "
                f"{piece!r}; expected key:organization:role[:project_id[:agent_id]]"
            )
        token, tenant_id, role_name = (p.strip() for p in parts[:3])
        if not token or not tenant_id:
            raise ValueError(f"Invalid auth key entry {piece!r}")
        project_id = parts[3].strip() if len(parts) >= 4 else None
        agent_id = parts[4].strip() if len(parts) == 5 else None
        if (project_id is not None and not project_id) or (agent_id is not None and not agent_id):
            raise ValueError(f"Invalid scoped auth key entry {piece!r}")
        out[token] = AuthPrincipal(
            tenant_id=tenant_id,
            role=Role.parse(role_name),
            subject=token[:8],
            project_id=project_id,
            agent_id=agent_id,
        )
    return out


def resolve_principal(
    settings: Settings,
    *,
    authorization: str | None,
    api_key: str | None,
) -> AuthPrincipal:
    if not settings.auth_enabled:
        return AuthPrincipal(
            tenant_id=DEFAULT_TENANT_ID,
            role=Role.ADMIN,
            subject="anonymous",
        )

    token = _extract_token(authorization=authorization, api_key=api_key)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    keys = parse_api_keys(settings.auth_api_keys)
    principal = keys.get(token)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal


def _extract_token(
    *, authorization: str | None, api_key: str | None
) -> str | None:
    if api_key and api_key.strip():
        return api_key.strip()
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return value.strip()
    return None


async def get_principal(
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header(alias="X-Api-Key")] = None,
    settings: Settings = Depends(get_settings),
) -> AuthPrincipal:
    principal = resolve_principal(
        settings, authorization=authorization, api_key=x_api_key
    )
    set_principal(principal)
    return principal


def require_role(minimum: Role):
    async def _dep(
        principal: AuthPrincipal = Depends(get_principal),
    ) -> AuthPrincipal:
        principal.require(minimum)
        return principal

    return _dep
