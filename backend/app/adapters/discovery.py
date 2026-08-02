"""Discover adapter packages installed in the worker environment."""

from __future__ import annotations

from importlib import metadata
from typing import Any

from app.adapters.base import OrchestratorAdapter, register_adapters
from app.core.logging import get_logger

ENTRY_POINT_GROUP = "agentflow.adapters"

logger = get_logger("adapters")

_plugins_loaded = False


class AdapterPluginError(RuntimeError):
    """Raised when an installed adapter plugin cannot be registered."""


def iter_entry_points() -> list[metadata.EntryPoint]:
    """Adapter entry points advertised by installed packages, ordered deterministically."""
    return sorted(
        metadata.entry_points(group=ENTRY_POINT_GROUP),
        key=lambda entry_point: (entry_point.name, entry_point.value),
    )


def _build_adapter(entry_point: metadata.EntryPoint) -> OrchestratorAdapter:
    try:
        factory: Any = entry_point.load()
    except Exception as exc:
        raise AdapterPluginError(
            f"Failed to load adapter plugin {entry_point.name!r} "
            f"from {entry_point.value!r}"
        ) from exc

    if not callable(factory):
        raise AdapterPluginError(
            f"Adapter plugin {entry_point.name!r} must expose a zero-argument factory"
        )

    try:
        adapter = factory()
    except Exception as exc:
        raise AdapterPluginError(
            f"Adapter plugin factory failed for {entry_point.name!r} "
            f"from {entry_point.value!r}"
        ) from exc

    if not isinstance(adapter, OrchestratorAdapter):
        raise AdapterPluginError(
            f"Adapter plugin {entry_point.name!r} factory must return "
            "an OrchestratorAdapter"
        )
    return adapter


def load_adapter_plugins() -> None:
    """Register installed adapter plugins on top of the built-in ones, once.

    Building a plugin imports third-party code that may register adapters of
    its own, so name conflicts are only decidable once every factory has run.
    The batch is therefore registered atomically at the end: any failure aborts
    startup with the registry left as it was.
    """
    global _plugins_loaded
    if _plugins_loaded:
        return

    adapters = [
        (entry_point.name, _build_adapter(entry_point))
        for entry_point in iter_entry_points()
    ]

    try:
        register_adapters(adapters)
    except ValueError as exc:
        raise AdapterPluginError(str(exc)) from exc

    _plugins_loaded = True
    if adapters:
        logger.info("adapters.plugins_loaded", adapters=[name for name, _ in adapters])
