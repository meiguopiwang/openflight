"""Tests for the LIS3DH zero-offset calibration helper."""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest

from openflight.inclinometer import AccelerationSample

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "hardware-test" / "calibrate_lis3dh.py"
spec = importlib.util.spec_from_file_location("calibrate_lis3dh", SCRIPT)
calibrate = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = calibrate
spec.loader.exec_module(calibrate)


def _tilted(pitch_deg: float, roll_deg: float) -> AccelerationSample:
    pitch = math.radians(pitch_deg)
    roll = math.radians(roll_deg)
    return AccelerationSample(
        0.0,
        math.sin(roll),
        math.cos(roll) * math.sin(pitch),
        math.cos(roll) * math.cos(pitch),
    )


def test_recommends_offsets_that_map_raw_readings_to_the_reference():
    # The user's unit: chip reads +3.35 deg sideways while a digital level reads 0.3 right high.
    samples = [_tilted(-1.4, 3.30), _tilted(-1.4, 3.40), _tilted(-1.4, 3.35)]

    result = calibrate.recommend_offsets(samples, reference_pitch=0.1, reference_roll=0.3)

    assert result.raw_roll == pytest.approx(3.35, abs=1e-3)
    assert result.roll_offset == pytest.approx(-3.05, abs=1e-3)
    assert result.pitch_offset == pytest.approx(0.1 - result.raw_pitch)
    assert result.raw_pitch == pytest.approx(-1.4, abs=0.01)
    assert result.roll_std == pytest.approx(0.0408, abs=1e-3)


def test_level_references_default_offsets_to_minus_the_raw_angles():
    samples = [_tilted(2.0, -1.0), _tilted(2.0, -1.0)]

    result = calibrate.recommend_offsets(samples)

    # Pitch and roll interact slightly when both tilt, so allow a thousandth of a degree.
    assert result.pitch_offset == pytest.approx(-2.0, abs=1e-3)
    assert result.roll_offset == pytest.approx(1.0, abs=1e-3)


def test_prints_both_recommended_flags():
    result = calibrate.recommend_offsets(
        [_tilted(-1.4, 3.35)] * 2, reference_pitch=0.1, reference_roll=0.3
    )

    lines = calibrate.format_report(result, reference_pitch=0.1, reference_roll=0.3)

    # Pitch reads -1.398 here, not -1.4: the 3.35 deg roll shrinks the Y gravity component.
    assert f"Recommended flag: --inclinometer-zero-offset {result.pitch_offset:+.3f}" in lines
    assert result.pitch_offset == pytest.approx(1.498, abs=1e-3)
    assert "Recommended flag: --inclinometer-roll-zero-offset -3.050" in lines
    assert "Reference roll: +0.300deg (positive = right side high)" in lines
