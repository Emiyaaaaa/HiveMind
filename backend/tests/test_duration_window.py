"""Tests for rolling p95 duration windows."""

from __future__ import annotations

import pytest

from app.core.duration_window import DurationWindow


def test_p95_requires_samples():
    window = DurationWindow(max_samples=10)
    assert window.p95() is None


def test_p95_computes_95th_percentile():
    window = DurationWindow(max_samples=100)
    for value in range(1, 21):
        window.record(float(value))

    assert window.p95() == 19.0


def test_record_ignores_negative_durations():
    window = DurationWindow(max_samples=10)
    window.record(-1.0)
    window.record(1.0)

    assert window.count() == 1
    assert window.p95() == 1.0


def test_window_respects_max_samples():
    window = DurationWindow(max_samples=3)
    window.record(1.0)
    window.record(2.0)
    window.record(3.0)
    window.record(100.0)

    assert window.count() == 3
    assert window.p95() == 100.0


def test_clear_resets_samples():
    window = DurationWindow(max_samples=10)
    window.record(5.0)
    window.clear()

    assert window.count() == 0
    assert window.p95() is None


def test_invalid_max_samples():
    with pytest.raises(ValueError):
        DurationWindow(max_samples=0)
