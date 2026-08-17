"""Official PydanticAI adapter plugin for AgentFlow."""

from agentflow_pydantic_ai.adapter import PydanticAIAdapter

__all__ = ["PydanticAIAdapter", "create_adapter"]


def create_adapter() -> PydanticAIAdapter:
    """Entry-point factory discovered through ``agentflow.adapters``."""
    return PydanticAIAdapter()
