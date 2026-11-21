"""LIS3DH transport, pitch math, filtering, and snapshot selection tests."""

import math

import pytest

from openflight.inclinometer import (
    LIS3DH,
    AccelerationSample,
    InclinometerService,
    LIS3DHIdentityError,
)
from openflight.inclinometer.service import pitch_degrees, roll_degrees


def _axis_bytes(value_g: float) -> list[int]:
    counts = round(value_g / 0.001)
    raw = (counts << 4) & 0xFFFF
    return [raw & 0xFF, raw >> 8]


class FakeBus:
    def __init__(self, *, identity=0x33, axes=(0.0, 0.0, 1.0)):
        self.identity = identity
        self.axes = axes
        self.writes = []
        self.closed = False

    def read_byte_data(self, address, register):
        assert address == 0x18
        assert register == LIS3DH.WHO_AM_I
        return self.identity

    def write_byte_data(self, address, register, value):
        self.writes.append((address, register, value))

    def read_i2c_block_data(self, address, register, length):
        assert (address, register, length) == (0x18, 0xA8, 6)
        return sum((_axis_bytes(axis) for axis in self.axes), [])

    def close(self):
        self.closed = True


def test_lis3dh_initializes_high_resolution_xyz_mode_and_reads_signed_axes():
    bus = FakeBus(axes=(-0.125, 0.25, 0.975))
    sensor = LIS3DH(bus=bus)

    sensor.initialize()
    sample = sensor.read(timestamp=123.0)
    sensor.close()

    assert bus.writes == [(0x18, 0x20, 0x57), (0x18, 0x23, 0x88)]
    assert sample == AccelerationSample(123.0, -0.125, 0.25, 0.975)
    assert bus.closed


def test_lis3dh_rejects_wrong_identity():
    sensor = LIS3DH(bus=FakeBus(identity=0x00))

    with pytest.raises(LIS3DHIdentityError, match="expected 0x33, got 0x00"):
        sensor.initialize()


def test_pitch_is_positive_when_sensor_y_tilts_back():
    angle = math.radians(12.0)
    sample = AccelerationSample(1.0, 0.0, math.sin(angle), math.cos(angle))

    assert pitch_degrees(sample) == pytest.approx(12.0)


def test_roll_is_positive_when_sensor_x_side_is_raised():
    angle = math.radians(4.0)
    sample = AccelerationSample(1.0, math.sin(angle), 0.0, math.cos(angle))

    assert roll_degrees(sample) == pytest.approx(4.0)
    assert pitch_degrees(sample) == pytest.approx(0.0)


def test_roll_and_pitch_stay_independent_when_both_tilt():
    pitch = math.radians(9.0)
    roll = math.radians(-4.0)
    # Gravity seen by a sensor pitched about X, then rolled about Y.
    sample = AccelerationSample(
        1.0,
        math.sin(roll),
        math.cos(roll) * math.sin(pitch),
        math.cos(roll) * math.cos(pitch),
    )

    assert roll_degrees(sample) == pytest.approx(-4.0)
    assert pitch_degrees(sample) == pytest.approx(
        math.degrees(math.asin(math.cos(roll) * math.sin(pitch)))
    )


def test_snapshot_applies_the_roll_offset_to_roll_and_the_pitch_offset_to_pitch():
    """The chip can sit crooked sideways; each axis has its own zero offset."""
    service = InclinometerService(
        sensor=None, zero_offset_deg=1.5, roll_zero_offset_deg=-3.07, window_samples=3
    )
    for timestamp, roll_deg in zip((1.0, 1.1, 1.2), (3.27, 3.47, 3.37)):
        angle = math.radians(roll_deg)
        snapshot = service.add_sample(
            AccelerationSample(timestamp, math.sin(angle), 0.0, math.cos(angle))
        )

    assert snapshot.raw_roll_deg == pytest.approx(3.37)
    assert snapshot.calibrated_roll_deg == pytest.approx(0.30)
    assert snapshot.calibrated_pitch_deg == pytest.approx(1.5)
    data = snapshot.to_dict()
    assert data["raw_roll_deg"] == 3.37
    assert data["calibrated_roll_deg"] == 0.3


def test_roll_offset_defaults_to_zero():
    service = InclinometerService(sensor=None, window_samples=2)
    angle = math.radians(2.0)
    for timestamp in (1.0, 1.1):
        snapshot = service.add_sample(
            AccelerationSample(timestamp, math.sin(angle), 0.0, math.cos(angle))
        )

    assert snapshot.calibrated_roll_deg == pytest.approx(snapshot.raw_roll_deg)


def test_service_applies_zero_offset_and_selects_preimpact_snapshot():
    service = InclinometerService(
        sensor=None,
        zero_offset_deg=1.5,
        window_samples=4,
        max_snapshot_age_s=2.0,
    )
    angle = math.radians(3.0)
    for timestamp in (9.0, 9.1, 9.2, 9.3, 10.1):
        service.add_sample(AccelerationSample(timestamp, 0.0, math.sin(angle), math.cos(angle)))

    selection = service.snapshot_for_impact(10.0)

    assert selection.status == "stable"
    assert selection.age_s == pytest.approx(0.7)
    assert selection.snapshot.timestamp == 9.3
    assert selection.snapshot.raw_pitch_deg == pytest.approx(3.0)
    assert selection.snapshot.calibrated_pitch_deg == pytest.approx(4.5)


def test_service_rejects_moving_window_and_stale_snapshot():
    service = InclinometerService(
        sensor=None,
        window_samples=4,
        max_pitch_std_deg=0.2,
        max_snapshot_age_s=1.0,
    )
    for timestamp, angle_deg in zip((1.0, 1.1, 1.2, 1.3), (0.0, 3.0, -2.0, 4.0)):
        angle = math.radians(angle_deg)
        assert (
            service.add_sample(AccelerationSample(timestamp, 0.0, math.sin(angle), math.cos(angle)))
            is None
        )
    assert service.snapshot_for_impact(1.4).status == "no_stable_preimpact_reading"

    for timestamp in (2.0, 2.1, 2.2, 2.3):
        service.add_sample(AccelerationSample(timestamp, 0.0, 0.0, 1.0))
    selection = service.snapshot_for_impact(4.0)
    assert selection.status == "stale"
    assert selection.snapshot is None
    assert selection.age_s == pytest.approx(1.7)


def test_service_rejects_non_gravity_acceleration():
    service = InclinometerService(sensor=None, window_samples=3)

    for timestamp in (1.0, 1.1, 1.2):
        assert service.add_sample(AccelerationSample(timestamp, 0.0, 0.0, 1.5)) is None

    assert service.snapshot_for_impact(1.3).status == "no_stable_preimpact_reading"


def test_service_does_not_reuse_old_position_after_movement():
    service = InclinometerService(sensor=None, window_samples=3, max_pitch_std_deg=0.2)
    for timestamp in (1.0, 1.1, 1.2):
        service.add_sample(AccelerationSample(timestamp, 0.0, 0.0, 1.0))
    assert service.snapshot_for_impact(1.25).status == "stable"

    moved = math.radians(8.0)
    service.add_sample(AccelerationSample(1.3, 0.0, math.sin(moved), math.cos(moved)))

    selection = service.snapshot_for_impact(1.35)
    assert selection.status == "moving"
    assert selection.snapshot is None


def _feed_still(service, start, count, *, pitch_deg=0.0, roll_deg=0.0, step=0.1):
    pitch = math.radians(pitch_deg)
    roll = math.radians(roll_deg)
    for index in range(count):
        service.add_sample(
            AccelerationSample(
                start + index * step,
                math.sin(roll),
                math.cos(roll) * math.sin(pitch),
                math.cos(roll) * math.cos(pitch),
            )
        )


def test_level_reading_averages_a_still_window():
    service = InclinometerService(sensor=None, sample_hz=10.0, window_samples=4)
    _feed_still(service, 10.0, 40, pitch_deg=-1.45, roll_deg=3.35)

    reading, status = service.level_reading(now=13.95, duration_s=3.0)

    assert status == "stable"
    assert reading.raw_pitch_deg == pytest.approx(-1.45, abs=0.01)
    assert reading.raw_roll_deg == pytest.approx(3.35, abs=1e-6)
    assert reading.snapshot_count >= 28
    assert reading.pitch_std_deg == pytest.approx(0.0, abs=1e-6)


def test_level_reading_needs_the_full_window_after_startup():
    service = InclinometerService(sensor=None, sample_hz=10.0, window_samples=4)
    _feed_still(service, 10.0, 12)

    reading, status = service.level_reading(now=11.15, duration_s=3.0)

    assert reading is None
    assert status == "settling"


def test_level_reading_refuses_when_the_unit_moved_in_the_window():
    service = InclinometerService(
        sensor=None, sample_hz=10.0, window_samples=4, max_pitch_std_deg=0.2
    )
    _feed_still(service, 10.0, 20)
    _feed_still(service, 12.0, 1, pitch_deg=8.0)  # a bump
    _feed_still(service, 12.1, 20)

    reading, status = service.level_reading(now=14.05, duration_s=3.0)

    assert reading is None
    assert status == "moving"


def test_level_reading_reports_a_sensor_error_in_the_window():
    service = InclinometerService(sensor=None, sample_hz=10.0, window_samples=4)
    _feed_still(service, 10.0, 40)
    service._last_error = "I2C read failed"  # pylint: disable=protected-access
    service._last_error_timestamp = 13.0  # pylint: disable=protected-access

    reading, status = service.level_reading(now=13.95, duration_s=3.0)

    assert reading is None
    assert status == "sensor_error"


def test_set_zero_offsets_applies_to_new_snapshots_and_drops_old_ones():
    service = InclinometerService(
        sensor=None, zero_offset_deg=1.663, roll_zero_offset_deg=-3.05, window_samples=3
    )
    _feed_still(service, 1.0, 5, pitch_deg=-1.45, roll_deg=3.35)
    assert service.snapshot_for_impact(1.45).snapshot.calibrated_pitch_deg == pytest.approx(
        0.213, abs=0.01
    )

    service.set_zero_offsets(zero_offset_deg=1.45, roll_zero_offset_deg=-3.35)

    # Snapshots taken with the old offsets must never reach a shot.
    assert service.snapshot_for_impact(1.45).snapshot is None
    _feed_still(service, 1.5, 1, pitch_deg=-1.45, roll_deg=3.35)
    snapshot = service.snapshot_for_impact(1.55).snapshot
    assert snapshot.calibrated_pitch_deg == pytest.approx(0.0, abs=0.01)
    assert snapshot.calibrated_roll_deg == pytest.approx(0.0, abs=1e-6)
    assert (service.zero_offset_deg, service.roll_zero_offset_deg) == (1.45, -3.35)
