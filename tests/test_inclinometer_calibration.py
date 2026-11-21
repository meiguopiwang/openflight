"""On-screen level calibration: offset maths, limits, and the saved record."""

import json
import math

import pytest

from openflight.inclinometer import LevelReading
from openflight.inclinometer.calibration import (
    MAX_ZERO_OFFSET_DEG,
    InclinometerCalibrationError,
    LevelCalibration,
    level_calibration_from_reading,
    load_level_calibration,
    save_level_calibration,
    undo_level_calibration,
)


def _reading(raw_pitch=-1.45, raw_roll=3.35):
    return LevelReading(
        raw_pitch_deg=raw_pitch,
        raw_roll_deg=raw_roll,
        pitch_std_deg=0.05,
        roll_std_deg=0.06,
        snapshot_count=30,
    )


def test_level_floor_offsets_cancel_the_raw_reading():
    calibration = level_calibration_from_reading(
        _reading(),
        previous_zero_offset_deg=1.663,
        previous_roll_zero_offset_deg=-3.05,
        calibrated_at="2026-11-05T22:40:00",
    )

    assert calibration.zero_offset_deg == pytest.approx(1.45)
    assert calibration.roll_zero_offset_deg == pytest.approx(-3.35)
    assert calibration.previous_zero_offset_deg == 1.663
    assert calibration.previous_roll_zero_offset_deg == -3.05
    assert calibration.method == "level"


@pytest.mark.parametrize(
    ("raw_pitch", "raw_roll", "axis"),
    [(-10.5, 0.0, "pitch"), (0.0, 10.5, "roll"), (12.0, -11.0, "pitch")],
)
def test_rejects_offsets_beyond_the_limit(raw_pitch, raw_roll, axis):
    """A large offset means the unit is not on a level floor or the chip is loose."""
    with pytest.raises(InclinometerCalibrationError, match=axis):
        level_calibration_from_reading(
            _reading(raw_pitch, raw_roll),
            previous_zero_offset_deg=0.0,
            previous_roll_zero_offset_deg=0.0,
            calibrated_at="2026-11-05T22:40:00",
        )


def test_accepts_offsets_exactly_at_the_limit():
    calibration = level_calibration_from_reading(
        _reading(-MAX_ZERO_OFFSET_DEG, MAX_ZERO_OFFSET_DEG),
        previous_zero_offset_deg=0.0,
        previous_roll_zero_offset_deg=0.0,
        calibrated_at="2026-11-05T22:40:00",
    )

    assert calibration.zero_offset_deg == MAX_ZERO_OFFSET_DEG
    assert calibration.roll_zero_offset_deg == -MAX_ZERO_OFFSET_DEG


def test_rejects_non_finite_readings():
    with pytest.raises(InclinometerCalibrationError, match="finite"):
        level_calibration_from_reading(
            _reading(math.nan, 0.0),
            previous_zero_offset_deg=0.0,
            previous_roll_zero_offset_deg=0.0,
            calibrated_at="2026-11-05T22:40:00",
        )


def test_undo_swaps_current_and_previous_offsets():
    calibration = level_calibration_from_reading(
        _reading(),
        previous_zero_offset_deg=1.663,
        previous_roll_zero_offset_deg=-3.05,
        calibrated_at="2026-11-05T22:40:00",
    )

    undone = undo_level_calibration(calibration, calibrated_at="2026-11-05T22:41:00")

    assert undone.zero_offset_deg == 1.663
    assert undone.roll_zero_offset_deg == -3.05
    assert undone.previous_zero_offset_deg == pytest.approx(1.45)
    assert undone.previous_roll_zero_offset_deg == pytest.approx(-3.35)
    assert undone.method == "undo"
    assert undone.calibrated_at == "2026-11-05T22:41:00"
    # Undoing the undo restores the calibration again.
    redone = undo_level_calibration(undone, calibrated_at="2026-11-05T22:42:00")
    assert redone.zero_offset_deg == pytest.approx(1.45)


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "inclinometer_calibration.json"
    calibration = level_calibration_from_reading(
        _reading(),
        previous_zero_offset_deg=1.663,
        previous_roll_zero_offset_deg=-3.05,
        calibrated_at="2026-11-05T22:40:00",
    )

    save_level_calibration(calibration, path)

    assert load_level_calibration(path) == calibration
    assert json.loads(path.read_text())["schema_version"] == 1


def test_load_returns_none_when_never_calibrated(tmp_path):
    assert load_level_calibration(tmp_path / "missing.json") is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda record: record.update(schema_version=2),
        lambda record: record.update(zero_offset_deg="1.5"),
        lambda record: record.update(roll_zero_offset_deg=True),
        lambda record: record.update(zero_offset_deg=MAX_ZERO_OFFSET_DEG + 0.1),
        lambda record: record.pop("roll_zero_offset_deg"),
        lambda record: record.update(method="guess"),
    ],
)
def test_load_rejects_invalid_records(tmp_path, mutate):
    path = tmp_path / "inclinometer_calibration.json"
    calibration = level_calibration_from_reading(
        _reading(),
        previous_zero_offset_deg=0.0,
        previous_roll_zero_offset_deg=0.0,
        calibrated_at="2026-11-05T22:40:00",
    )
    save_level_calibration(calibration, path)
    record = json.loads(path.read_text())
    mutate(record)
    path.write_text(json.dumps(record))

    with pytest.raises(InclinometerCalibrationError):
        load_level_calibration(path)


def test_load_rejects_non_object_json(tmp_path):
    path = tmp_path / "inclinometer_calibration.json"
    path.write_text("[1, 2]")

    with pytest.raises(InclinometerCalibrationError):
        load_level_calibration(path)


def test_record_from_command_line_values_keeps_the_values_and_has_no_previous():
    """Used once to migrate the startup flags into the saved file."""
    record = LevelCalibration.from_values(
        zero_offset_deg=1.663,
        roll_zero_offset_deg=-3.05,
        calibrated_at="2026-11-05T22:30:00",
    )

    assert record.zero_offset_deg == 1.663
    assert record.roll_zero_offset_deg == -3.05
    assert record.previous_zero_offset_deg is None
    assert record.method == "manual"


def test_undo_without_a_previous_calibration_is_refused():
    record = LevelCalibration.from_values(
        zero_offset_deg=1.663,
        roll_zero_offset_deg=-3.05,
        calibrated_at="2026-11-05T22:30:00",
    )

    with pytest.raises(InclinometerCalibrationError, match="nothing to undo"):
        undo_level_calibration(record, calibrated_at="2026-11-05T22:41:00")
