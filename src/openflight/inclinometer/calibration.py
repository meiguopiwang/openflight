"""On-screen level calibration of the LIS3DH zero offsets and its saved record."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from ..json_files import atomic_write_json
from .models import LevelReading

SCHEMA_VERSION = 1
# A level floor only has to cancel the chip's own mounting error. Anything
# larger means the unit was not on a level floor or the board has come loose.
MAX_ZERO_OFFSET_DEG = 10.0
METHODS = ("level", "undo", "manual")


class InclinometerCalibrationError(ValueError):
    """A calibration would be unsafe, or a saved record is invalid."""


def _checked_offset(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InclinometerCalibrationError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise InclinometerCalibrationError(f"{name} must be finite")
    if abs(number) > MAX_ZERO_OFFSET_DEG:
        raise InclinometerCalibrationError(
            f"{name} {number:+.2f}deg exceeds the {MAX_ZERO_OFFSET_DEG:.0f}deg limit; "
            "check the unit is on a level floor and the sensor is mounted firmly"
        )
    return number


def _optional_offset(name: str, value: object) -> float | None:
    return None if value is None else _checked_offset(name, value)


@dataclass(frozen=True)
class LevelCalibration:
    """Zero offsets in use, how they were set, and the values they replaced."""

    zero_offset_deg: float
    roll_zero_offset_deg: float
    calibrated_at: str
    method: str
    previous_zero_offset_deg: float | None = None
    previous_roll_zero_offset_deg: float | None = None
    raw_pitch_deg: float | None = None
    raw_roll_deg: float | None = None
    snapshot_count: int | None = None

    @classmethod
    def from_values(
        cls, *, zero_offset_deg: float, roll_zero_offset_deg: float, calibrated_at: str
    ) -> "LevelCalibration":
        """Record offsets measured elsewhere, e.g. migrated from startup flags."""
        return cls(
            zero_offset_deg=_checked_offset("pitch zero offset", zero_offset_deg),
            roll_zero_offset_deg=_checked_offset("roll zero offset", roll_zero_offset_deg),
            calibrated_at=calibrated_at,
            method="manual",
        )

    @property
    def can_undo(self) -> bool:
        """Whether the values this calibration replaced are known."""
        return (
            self.previous_zero_offset_deg is not None
            and self.previous_roll_zero_offset_deg is not None
        )

    def to_dict(self) -> dict:
        """Return the JSON record, including its schema version."""
        return {"schema_version": SCHEMA_VERSION, **asdict(self)}


def level_calibration_from_reading(
    reading: LevelReading,
    *,
    previous_zero_offset_deg: float,
    previous_roll_zero_offset_deg: float,
    calibrated_at: str,
) -> LevelCalibration:
    """Offsets that make a still unit on a level floor read 0 deg pitch and roll."""
    return LevelCalibration(
        zero_offset_deg=_checked_offset("pitch zero offset", -reading.raw_pitch_deg),
        roll_zero_offset_deg=_checked_offset("roll zero offset", -reading.raw_roll_deg),
        calibrated_at=calibrated_at,
        method="level",
        previous_zero_offset_deg=previous_zero_offset_deg,
        previous_roll_zero_offset_deg=previous_roll_zero_offset_deg,
        raw_pitch_deg=reading.raw_pitch_deg,
        raw_roll_deg=reading.raw_roll_deg,
        snapshot_count=reading.snapshot_count,
    )


def undo_level_calibration(current: LevelCalibration, *, calibrated_at: str) -> LevelCalibration:
    """Restore the replaced offsets; undoing again restores these ones."""
    if not current.can_undo:
        raise InclinometerCalibrationError("nothing to undo: the previous offsets are unknown")
    return replace(
        current,
        zero_offset_deg=current.previous_zero_offset_deg,
        roll_zero_offset_deg=current.previous_roll_zero_offset_deg,
        previous_zero_offset_deg=current.zero_offset_deg,
        previous_roll_zero_offset_deg=current.roll_zero_offset_deg,
        calibrated_at=calibrated_at,
        method="undo",
    )


def save_level_calibration(calibration: LevelCalibration, path: Path | str) -> None:
    """Atomically persist the calibration record."""
    atomic_write_json(path, calibration.to_dict())


def load_level_calibration(path: Path | str) -> LevelCalibration | None:
    """Load and validate the saved record; None when the unit was never calibrated."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise InclinometerCalibrationError(
            f"saved calibration is not valid JSON: {error}"
        ) from error
    if not isinstance(record, dict) or record.get("schema_version") != SCHEMA_VERSION:
        raise InclinometerCalibrationError(
            f"saved calibration schema_version must be {SCHEMA_VERSION}"
        )
    method = record.get("method")
    if method not in METHODS:
        raise InclinometerCalibrationError(f"saved calibration method must be one of {METHODS}")
    if "zero_offset_deg" not in record or "roll_zero_offset_deg" not in record:
        raise InclinometerCalibrationError("saved calibration is missing an offset")
    snapshot_count = record.get("snapshot_count")
    return LevelCalibration(
        zero_offset_deg=_checked_offset("pitch zero offset", record["zero_offset_deg"]),
        roll_zero_offset_deg=_checked_offset("roll zero offset", record["roll_zero_offset_deg"]),
        calibrated_at=str(record.get("calibrated_at", "")),
        method=method,
        previous_zero_offset_deg=_optional_offset(
            "previous pitch zero offset", record.get("previous_zero_offset_deg")
        ),
        previous_roll_zero_offset_deg=_optional_offset(
            "previous roll zero offset", record.get("previous_roll_zero_offset_deg")
        ),
        raw_pitch_deg=record.get("raw_pitch_deg"),
        raw_roll_deg=record.get("raw_roll_deg"),
        snapshot_count=int(snapshot_count) if snapshot_count is not None else None,
    )


__all__ = [
    "InclinometerCalibrationError",
    "LevelCalibration",
    "MAX_ZERO_OFFSET_DEG",
    "level_calibration_from_reading",
    "load_level_calibration",
    "save_level_calibration",
    "undo_level_calibration",
]
