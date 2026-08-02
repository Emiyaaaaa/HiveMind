from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
from typing import Any

import pytest

from app.adapters import base, discovery
from app.adapters.base import AdapterContext, AdapterResult, OrchestratorAdapter
from app.adapters.discovery import AdapterPluginError, load_adapter_plugins
from app.models.run import RunStatus


class _PluginAdapter(OrchestratorAdapter):
    async def run(self, ctx: AdapterContext) -> AdapterResult:
        return AdapterResult(status=RunStatus.SUCCEEDED)


def create_plugin_adapter() -> OrchestratorAdapter:
    """Factory target resolved through a real `EntryPoint.load()`."""
    return _PluginAdapter()


@dataclass
class _EntryPoint:
    """Stand-in for targets a real entry point cannot resolve (import errors, non-callables)."""

    name: str
    value: str
    target: Any

    def load(self) -> Any:
        if isinstance(self.target, Exception):
            raise self.target
        return self.target


@pytest.fixture(autouse=True)
def isolate_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(base, "_registry", dict(base._registry))
    monkeypatch.setattr(discovery, "_plugins_loaded", False)


def _set_entry_points(monkeypatch: pytest.MonkeyPatch, entry_points: list[Any]) -> None:
    monkeypatch.setattr(discovery, "iter_entry_points", lambda: entry_points)


def test_iter_entry_points_queries_the_declared_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guards the group name and the `entry_points` signature against silent drift."""
    captured: dict[str, Any] = {}

    def fake_entry_points(**params: Any) -> list[Any]:
        captured.update(params)
        return []

    monkeypatch.setattr(discovery.metadata, "entry_points", fake_entry_points)

    assert discovery.iter_entry_points() == []
    assert captured == {"group": "agentflow.adapters"}


def test_load_adapter_plugins_resolves_a_real_entry_point(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercises real `EntryPoint.load()` import machinery rather than a stub."""
    entry_point = metadata.EntryPoint(
        name="real-plugin",
        value="tests.test_adapter_plugins:create_plugin_adapter",
        group=discovery.ENTRY_POINT_GROUP,
    )
    _set_entry_points(monkeypatch, [entry_point])

    load_adapter_plugins()

    assert isinstance(base.get_adapter("real-plugin"), _PluginAdapter)
    assert base.get_adapter("real-plugin").name == "real-plugin"


def test_load_adapter_plugins_registers_factory_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def create_adapter() -> OrchestratorAdapter:
        nonlocal calls
        calls += 1
        return _PluginAdapter()

    _set_entry_points(
        monkeypatch,
        [_EntryPoint("test-plugin", "test_plugin:create_adapter", create_adapter)],
    )

    load_adapter_plugins()
    load_adapter_plugins()

    assert calls == 1
    assert isinstance(base.get_adapter("test-plugin"), _PluginAdapter)
    assert "test-plugin" in base.list_adapters()


def test_load_adapter_plugins_rejects_registered_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = base.get_adapter("echo")
    _set_entry_points(
        monkeypatch,
        [_EntryPoint("echo", "test_plugin:create_adapter", _PluginAdapter)],
    )

    with pytest.raises(AdapterPluginError, match="already registered"):
        load_adapter_plugins()

    assert base.get_adapter("echo") is original


def test_load_adapter_plugins_wraps_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_entry_points(
        monkeypatch,
        [_EntryPoint("broken", "broken:create_adapter", ImportError("missing dependency"))],
    )

    with pytest.raises(AdapterPluginError, match="broken:create_adapter") as exc_info:
        load_adapter_plugins()

    assert isinstance(exc_info.value.__cause__, ImportError)


def test_load_adapter_plugins_does_not_partially_register(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_entry_points(
        monkeypatch,
        [
            _EntryPoint("first", "first:create_adapter", _PluginAdapter),
            _EntryPoint("second", "second:create_adapter", lambda: object()),
        ],
    )

    with pytest.raises(AdapterPluginError, match="OrchestratorAdapter"):
        load_adapter_plugins()

    assert "first" not in base.list_adapters()


def test_load_adapter_plugins_rolls_back_when_a_factory_self_registers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plugin registering itself on import must not leave the batch half-applied."""

    def self_registering_factory() -> OrchestratorAdapter:
        base.register_adapter("second", _PluginAdapter())
        return _PluginAdapter()

    _set_entry_points(
        monkeypatch,
        [
            _EntryPoint("first", "first:create_adapter", _PluginAdapter),
            _EntryPoint("second", "second:create_adapter", self_registering_factory),
        ],
    )

    with pytest.raises(AdapterPluginError, match="already registered"):
        load_adapter_plugins()

    assert "first" not in base.list_adapters()


def test_load_adapter_plugins_rejects_one_instance_under_two_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`get_adapter(name).name == name` is what RunService dispatches on."""
    shared = _PluginAdapter()
    _set_entry_points(
        monkeypatch,
        [
            _EntryPoint("one", "shared:create_adapter", lambda: shared),
            _EntryPoint("two", "shared:create_adapter", lambda: shared),
        ],
    )

    with pytest.raises(AdapterPluginError, match="instance already registered"):
        load_adapter_plugins()

    assert "one" not in base.list_adapters()
    assert "two" not in base.list_adapters()


@pytest.mark.parametrize(
    ("target", "message"),
    [
        (object(), "zero-argument factory"),
        (lambda: object(), "OrchestratorAdapter"),
    ],
)
def test_load_adapter_plugins_validates_factory(
    monkeypatch: pytest.MonkeyPatch,
    target: Any,
    message: str,
) -> None:
    _set_entry_points(
        monkeypatch,
        [_EntryPoint("invalid", "invalid:create_adapter", target)],
    )

    with pytest.raises(AdapterPluginError, match=message):
        load_adapter_plugins()


def test_register_adapter_rejects_a_duplicate_name() -> None:
    base.register_adapter("dup", _PluginAdapter())

    with pytest.raises(ValueError, match="Adapter already registered"):
        base.register_adapter("dup", _PluginAdapter())


def test_register_adapters_is_atomic() -> None:
    before = base.list_adapters()

    with pytest.raises(ValueError):
        base.register_adapters([("fresh", _PluginAdapter()), ("echo", _PluginAdapter())])

    assert base.list_adapters() == before
