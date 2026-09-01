from pydantic import BaseModel, Field


class EraseRunDataResponse(BaseModel):
    run_id: str
    messages_deleted: int
    checkpoints_deleted: int


class EraseTenantDataResponse(BaseModel):
    tenant_id: str
    runs_processed: int
    messages_deleted: int
    checkpoints_deleted: int


class RetentionPurgeResponse(BaseModel):
    tenant_id: str
    runs_purged: int
    messages_deleted: int
    checkpoints_deleted: int


class RetentionPurgeRequest(BaseModel):
    """Optional override for tenant TTL purge (admin-only background job)."""

    tenant_id: str | None = Field(
        default=None,
        description="Purge one tenant; omit to sweep all tenants with TTL configured.",
    )
    dry_run: bool = Field(
        default=False,
        description="When true, report candidates without deleting.",
    )
