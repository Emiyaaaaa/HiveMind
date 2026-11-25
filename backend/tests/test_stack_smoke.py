"""In-process run of the Java-stack smoke checks."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ci" / "java_stack_smoke.py"


def _load_smoke():
    spec = importlib.util.spec_from_file_location("java_stack_smoke", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_stack_smoke_against_api(client):
    smoke = _load_smoke()
    await smoke.run_checks(client)
