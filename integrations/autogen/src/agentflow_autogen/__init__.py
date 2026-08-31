"""Official AutoGen adapter plugin for AgentFlow."""

from agentflow_autogen.adapter import AutoGenAdapter

__all__ = ["AutoGenAdapter", "create_adapter"]


def create_adapter() -> AutoGenAdapter:
    """Entry-point factory discovered through ``agentflow.adapters``."""
    return AutoGenAdapter()
