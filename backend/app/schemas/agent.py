from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    adapter: str = "echo"
    config: dict[str, Any] = Field(default_factory=dict)


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    adapter: str
    config: dict[str, Any]
    created_at: datetime
    updated_at: datetime
