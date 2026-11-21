"""Server integration for per-shot LIS3DH tilt compensation."""

import json
import math
import sys
from datetime import datetime
from types import SimpleNamespace

import pytest

from openflight import server
from openflight.inclinometer import LevelReading, OrientationSnapshot, SnapshotSelection
from openflight.inclinometer.calibration import (
    LevelCalibration,
    load_level_calibration,
    save_level_calibration,
)
from openflight.iwr6843.calibration import Calibration
from openflight.launch_monitor import Shot
from openflight.session_logger import SessionLogger


class FakeInclinometer:
    def __init__(self, selection, last_error=None):
        self.selection = selection
        self.impact_timestamp = None
        self.last_error = last_error

    def snapshot_for_impact(self, impact_timestamp):
        self.impact_timestamp = impact_timestamp
        return self.selection


def _stable_selection():
    return SnapshotSelection(
        snapshot=OrientationSnapshot(
            timestamp=99.8,
            x_g=0.0,
            y_g=0.0523,
            z_g=0.9986,
            gravity_g=1.0,
            raw_pitch_deg=3.0,
            calibrated_pitch_deg=4.5,
            pitch_std_deg=0.1,
            sample_count=8,
            raw_roll_deg=-1.0,
            calibrated_roll_deg=-4.07,
        ),
        status="stable",
        age_s=0.2,
    )


def test_server_passes_effective_preimpact_tilt_to_iwr(monkeypatch):
    sensor = FakeInclinometer(_stable_selection())
    calibration = Calibration.identity()
    calibration.tilt_rad = math.radians(11.5)
    seen = {}

    def process_shot(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(capture=None, measurement=None, club_path=None)

    monkeypatch.setattr(server, "inclinometer_service", sensor)
    monkeypatch.setattr(server, "inclinometer_runtime_config", {"zero_offset_deg": 1.5})
    monkeypatch.setattr(
        server,
        "iwr6843_runtime",
        SimpleNamespace(calibration=calibration, process_shot=process_shot),
    )
    monkeypatch.setattr(server, "get_session_logger", lambda: None)
    shot = Shot(ball_speed_mph=100.0, timestamp=datetime.now(), impact_timestamp=100.0)

    server._snapshot_inclinometer_for_shot(shot)
    server._process_iwr6843_angle(shot)

    assert sensor.impact_timestamp == 100.0
    assert shot.inclinometer["configured_iwr_tilt_deg"] == 11.5
    assert shot.inclinometer["effective_iwr_tilt_deg"] == 16.0
    assert shot.inclinometer["age_s"] == 0.2
    assert seen["tilt_deg"] == 16.0


def test_server_preserves_configured_tilt_without_stable_snapshot(monkeypatch):
    sensor = FakeInclinometer(
        SnapshotSelection(snapshot=None, status="no_stable_preimpact_reading")
    )
    calibration = Calibration.identity()
    seen = {}

    def process_shot(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(capture=None, measurement=None, club_path=None)

    monkeypatch.setattr(server, "inclinometer_service", sensor)
    monkeypatch.setattr(server, "inclinometer_runtime_config", {"zero_offset_deg": 1.5})
    monkeypatch.setattr(
        server,
        "iwr6843_runtime",
        SimpleNamespace(calibration=calibration, process_shot=process_shot),
    )
    monkeypatch.setattr(server, "get_session_logger", lambda: None)
    shot = Shot(ball_speed_mph=100.0, timestamp=datetime.now(), impact_timestamp=100.0)

    server._snapshot_inclinometer_for_shot(shot)
    server._process_iwr6843_angle(shot)

    assert shot.inclinometer["applied"] is False
    assert shot.inclinometer["status"] == "no_stable_preimpact_reading"
    assert seen["tilt_deg"] is None


def test_init_inclinometer_is_fail_soft(monkeypatch):
    class BrokenSensor:
        def __init__(self, **_kwargs):
            pass

    class BrokenService:
        def __init__(self, _sensor, **_kwargs):
            pass

        def start(self):
            raise OSError("I2C unavailable")

        def stop(self):
            pass

    monkeypatch.setattr("openflight.inclinometer.LIS3DH", BrokenSensor)
    monkeypatch.setattr("openflight.inclinometer.InclinometerService", BrokenService)
    monkeypatch.setattr(server, "log_session_error", lambda *_args, **_kwargs: None)

    offsets = server.InclinometerOffsets(1.5, -3.07, "command_line", "command_line", None)
    assert server.init_inclinometer(offsets=offsets) is False
    assert server.inclinometer_service is None
    assert server.inclinometer_runtime_config["requested"] is True
    assert server.inclinometer_runtime_config["roll_zero_offset_deg"] == -3.07
    assert server.inclinometer_runtime_config["error"] == "I2C unavailable"


def test_inclinometer_flag_requires_iwr6843(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["openflight-server", "--inclinometer"])

    with pytest.raises(SystemExit, match="2"):
        server.main()


def test_shot_dict_includes_inclinometer_provenance():
    shot = Shot(ball_speed_mph=100.0, timestamp=datetime.now())
    shot.inclinometer = {"applied": True, "effective_iwr_tilt_deg": 16.0}

    assert server.shot_to_dict(shot)["inclinometer"] == shot.inclinometer


def test_session_log_records_orientation_used_for_shot(tmp_path):
    logger = SessionLogger(log_dir=tmp_path, enabled=True)
    logger.start_session(mode="rolling-buffer", trigger_type="sound")
    orientation = {
        "applied": True,
        "calibrated_pitch_deg": 4.5,
        "effective_iwr_tilt_deg": 16.0,
    }

    shot = Shot(
        ball_speed_mph=100.0,
        club_speed_mph=70.0,
        timestamp=datetime.now(),
        peak_magnitude=10.0,
        inclinometer=orientation,
    )
    logger.log_shot(shot)

    entry = json.loads(logger.session_path.read_text().strip().splitlines()[-1])
    assert entry["type"] == "shot_detected"
    assert entry["inclinometer"] == orientation
    logger.end_session()


def _get_level(monkeypatch, sensor, *, tilt_deg=None):
    monkeypatch.setattr(server, "inclinometer_service", sensor)
    monkeypatch.setattr(
        server,
        "inclinometer_runtime_config",
        {"offset_sources": {"pitch": "default", "roll": "default"}, "level_calibration": None},
    )
    if tilt_deg is None:
        monkeypatch.setattr(server, "iwr6843_runtime", None)
    else:
        calibration = Calibration.identity()
        calibration.tilt_rad = math.radians(tilt_deg)
        monkeypatch.setattr(server, "iwr6843_runtime", SimpleNamespace(calibration=calibration))
    return server.app.test_client().get("/api/inclinometer/level")


def test_level_endpoint_is_404_without_an_inclinometer(monkeypatch):
    response = _get_level(monkeypatch, None)

    assert response.status_code == 404
    assert response.get_json() == {"enabled": False, "status": "unavailable"}


def test_level_endpoint_reports_current_tilt_lean_and_radar_tilt(monkeypatch):
    sensor = FakeInclinometer(_stable_selection())
    monkeypatch.setattr(server.time, "time", lambda: 100.0)

    response = _get_level(monkeypatch, sensor, tilt_deg=11.5)

    assert response.status_code == 200
    assert response.get_json() == {
        "enabled": True,
        "status": "stable",
        "age_s": 0.2,
        "pitch_deg": 4.5,
        "roll_deg": -4.07,
        "configured_iwr_tilt_deg": 11.5,
        "radar_tilt_deg": 16.0,
        "error": None,
        "calibration": {
            "pitch_source": "default",
            "roll_source": "default",
            "calibrated_at": None,
            "can_calibrate": True,
            "can_undo": False,
        },
    }
    assert sensor.impact_timestamp == 100.0


def test_level_endpoint_omits_radar_tilt_without_iwr(monkeypatch):
    body = _get_level(monkeypatch, FakeInclinometer(_stable_selection())).get_json()

    assert body["pitch_deg"] == 4.5
    assert body["roll_deg"] == -4.07
    assert body["configured_iwr_tilt_deg"] is None
    assert body["radar_tilt_deg"] is None


@pytest.mark.parametrize(
    "status",
    ["moving", "stale", "no_stable_preimpact_reading", "sensor_error"],
)
def test_level_endpoint_withholds_angles_without_a_stable_reading(monkeypatch, status):
    sensor = FakeInclinometer(
        SnapshotSelection(snapshot=None, status=status, age_s=None),
        last_error="I2C read failed" if status == "sensor_error" else None,
    )

    response = _get_level(monkeypatch, sensor, tilt_deg=9.4)

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == status
    assert body["pitch_deg"] is None
    assert body["roll_deg"] is None
    assert body["radar_tilt_deg"] is None
    assert body["configured_iwr_tilt_deg"] == 9.4
    assert body["error"] == ("I2C read failed" if status == "sensor_error" else None)


def test_level_and_shot_use_the_same_radar_tilt(monkeypatch):
    """One helper owns configured tilt + calibrated pitch for shots and the live readout."""
    sensor = FakeInclinometer(_stable_selection())
    level = _get_level(monkeypatch, sensor, tilt_deg=11.5).get_json()
    monkeypatch.setattr(server, "inclinometer_runtime_config", {"zero_offset_deg": 1.5})
    shot = Shot(ball_speed_mph=100.0, timestamp=datetime.now(), impact_timestamp=100.0)

    server._snapshot_inclinometer_for_shot(shot)

    assert level["radar_tilt_deg"] == shot.inclinometer["effective_iwr_tilt_deg"]
    assert shot.inclinometer["raw_roll_deg"] == -1.0
    assert shot.inclinometer["calibrated_roll_deg"] == -4.07


def test_init_inclinometer_passes_both_zero_offsets_and_records_them(monkeypatch):
    seen = {}

    class Sensor:
        def __init__(self, **_kwargs):
            pass

    class Service:
        sample_hz = 10.0

        def __init__(self, _sensor, **kwargs):
            seen.update(kwargs)

        def start(self):
            pass

        def wait_for_stable(self, timeout_s):
            return SnapshotSelection(snapshot=None, status="no_stable_preimpact_reading")

    monkeypatch.setattr("openflight.inclinometer.LIS3DH", Sensor)
    monkeypatch.setattr("openflight.inclinometer.InclinometerService", Service)
    monkeypatch.setattr(server, "inclinometer_service", None)

    saved = LevelCalibration.from_values(
        zero_offset_deg=1.663, roll_zero_offset_deg=-3.07, calibrated_at="2026-11-05T22:30:00"
    )
    offsets = server.InclinometerOffsets(1.663, -3.07, "command_line", "saved", saved)

    assert server.init_inclinometer(offsets=offsets) is True
    assert seen == {"zero_offset_deg": 1.663, "roll_zero_offset_deg": -3.07}
    assert server.inclinometer_runtime_config["zero_offset_deg"] == 1.663
    assert server.inclinometer_runtime_config["roll_zero_offset_deg"] == -3.07
    assert server.inclinometer_runtime_config["offset_sources"] == {
        "pitch": "command_line",
        "roll": "saved",
    }
    assert server.inclinometer_runtime_config["level_calibration"] == saved.to_dict()


def test_roll_zero_offset_flag_rejects_non_numbers(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "openflight-server",
            "--iwr6843",
            "--inclinometer",
            "--inclinometer-roll-zero-offset",
            "abc",
        ],
    )

    with pytest.raises(SystemExit, match="2"):
        server.main()
    err = capsys.readouterr().err
    assert "--inclinometer-roll-zero-offset: invalid float value: 'abc'" in err


# ---------------------------------------------------------------- level calibration


class FakeCalibratingInclinometer(FakeInclinometer):
    def __init__(self, reading=None, status="stable", zero=1.663, roll_zero=-3.05):
        super().__init__(_stable_selection())
        self.reading = reading or LevelReading(
            raw_pitch_deg=-1.45,
            raw_roll_deg=3.35,
            pitch_std_deg=0.05,
            roll_std_deg=0.06,
            snapshot_count=30,
        )
        self.status = status
        self.zero_offset_deg = zero
        self.roll_zero_offset_deg = roll_zero
        self.applied = []

    def level_reading(self, *, now=None, duration_s=3.0):
        return (self.reading if self.status == "stable" else None), self.status

    def set_zero_offsets(self, *, zero_offset_deg, roll_zero_offset_deg):
        self.applied.append((zero_offset_deg, roll_zero_offset_deg))
        self.zero_offset_deg = zero_offset_deg
        self.roll_zero_offset_deg = roll_zero_offset_deg


@pytest.fixture
def calibration_path(tmp_path, monkeypatch):
    path = tmp_path / "inclinometer_calibration.json"
    monkeypatch.setattr(server, "INCLINOMETER_CALIBRATION_PATH", path)
    return path


def _install(monkeypatch, sensor, *, sources=("saved", "saved"), saved=None):
    monkeypatch.setattr(server, "inclinometer_service", sensor)
    monkeypatch.setattr(server, "iwr6843_runtime", None)
    monkeypatch.setattr(
        server,
        "inclinometer_runtime_config",
        {
            "enabled": True,
            "zero_offset_deg": sensor.zero_offset_deg if sensor else 0.0,
            "roll_zero_offset_deg": sensor.roll_zero_offset_deg if sensor else 0.0,
            "offset_sources": {"pitch": sources[0], "roll": sources[1]},
            "level_calibration": saved.to_dict() if saved else None,
        },
    )
    logged = []
    monkeypatch.setattr(
        server,
        "get_session_logger",
        lambda: SimpleNamespace(
            log_config_change=lambda config, source: logged.append((config, source))
        ),
    )
    return logged


def _post(path, body=None):
    return server.app.test_client().post(path, json=body if body is not None else {})


# -- startup resolution: explicit flags win per axis, then the saved file, then 0


def test_resolve_offsets_defaults_to_zero_without_flags_or_file(calibration_path):
    resolved = server._resolve_inclinometer_offsets(explicit_pitch=None, explicit_roll=None)

    assert resolved == server.InclinometerOffsets(0.0, 0.0, "default", "default", None)


def test_resolve_offsets_uses_the_saved_calibration(calibration_path):
    saved = LevelCalibration.from_values(
        zero_offset_deg=1.45, roll_zero_offset_deg=-3.35, calibrated_at="2026-11-05T22:40:00"
    )
    save_level_calibration(saved, calibration_path)

    resolved = server._resolve_inclinometer_offsets(explicit_pitch=None, explicit_roll=None)

    assert resolved == server.InclinometerOffsets(1.45, -3.35, "saved", "saved", saved)


def test_resolve_offsets_lets_each_explicit_flag_win_its_axis(calibration_path):
    saved = LevelCalibration.from_values(
        zero_offset_deg=1.45, roll_zero_offset_deg=-3.35, calibrated_at="2026-11-05T22:40:00"
    )
    save_level_calibration(saved, calibration_path)

    resolved = server._resolve_inclinometer_offsets(explicit_pitch=1.663, explicit_roll=None)

    assert (resolved.zero_offset_deg, resolved.pitch_source) == (1.663, "command_line")
    assert (resolved.roll_zero_offset_deg, resolved.roll_source) == (-3.35, "saved")


def test_resolve_offsets_ignores_an_invalid_saved_file(calibration_path, caplog):
    calibration_path.write_text('{"schema_version": 99}')

    resolved = server._resolve_inclinometer_offsets(explicit_pitch=None, explicit_roll=-3.05)

    assert resolved == server.InclinometerOffsets(0.0, -3.05, "default", "command_line", None)
    assert "Ignoring invalid saved inclinometer calibration" in caplog.text


def test_offset_flags_default_to_unset_so_a_saved_file_can_apply(monkeypatch):
    """Offsets resolve right after argument checks, before any hardware starts."""
    seen = {}

    def stop_after_resolving(**kwargs):
        seen.update(kwargs)
        raise SystemExit(0)

    monkeypatch.setattr(server, "_resolve_inclinometer_offsets", stop_after_resolving)
    monkeypatch.setattr(sys, "argv", ["openflight-server", "--iwr6843", "--inclinometer"])

    with pytest.raises(SystemExit):
        server.main()

    assert seen == {"explicit_pitch": None, "explicit_roll": None}


def test_explicit_offset_flags_reach_the_resolver(monkeypatch):
    seen = {}

    def stop_after_resolving(**kwargs):
        seen.update(kwargs)
        raise SystemExit(0)

    monkeypatch.setattr(server, "_resolve_inclinometer_offsets", stop_after_resolving)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "openflight-server",
            "--iwr6843",
            "--inclinometer",
            "--inclinometer-zero-offset",
            "+1.663",
            "--inclinometer-roll-zero-offset",
            "-3.05",
        ],
    )

    with pytest.raises(SystemExit):
        server.main()

    assert seen == {"explicit_pitch": 1.663, "explicit_roll": -3.05}


# -- POST /api/inclinometer/level-calibration


def test_calibration_is_404_without_an_inclinometer(monkeypatch, calibration_path):
    monkeypatch.setattr(server, "inclinometer_service", None)

    response = _post("/api/inclinometer/level-calibration", {"apply": True})

    assert response.status_code == 404


def test_calibration_preview_proposes_offsets_without_saving(monkeypatch, calibration_path):
    sensor = FakeCalibratingInclinometer()
    _install(monkeypatch, sensor)

    response = _post("/api/inclinometer/level-calibration", {"apply": False})

    assert response.status_code == 200
    body = response.get_json()
    assert body["applied"] is False
    assert body["current"] == {"zero_offset_deg": 1.663, "roll_zero_offset_deg": -3.05}
    assert body["proposed"] == {"zero_offset_deg": 1.45, "roll_zero_offset_deg": -3.35}
    assert body["change"] == {"pitch_deg": -0.213, "roll_deg": -0.3}
    assert not calibration_path.exists()
    assert sensor.applied == []


def test_calibration_apply_saves_applies_and_logs(monkeypatch, calibration_path):
    sensor = FakeCalibratingInclinometer()
    logged = _install(monkeypatch, sensor, sources=("default", "default"))

    response = _post("/api/inclinometer/level-calibration", {"apply": True})

    assert response.status_code == 200
    body = response.get_json()
    assert body["applied"] is True
    assert sensor.applied == [(1.45, -3.35)]
    saved = load_level_calibration(calibration_path)
    assert (saved.zero_offset_deg, saved.roll_zero_offset_deg) == (1.45, -3.35)
    assert (saved.previous_zero_offset_deg, saved.previous_roll_zero_offset_deg) == (1.663, -3.05)
    assert server.inclinometer_runtime_config["offset_sources"] == {
        "pitch": "saved",
        "roll": "saved",
    }
    assert server.inclinometer_runtime_config["zero_offset_deg"] == 1.45
    assert server.inclinometer_runtime_config["roll_zero_offset_deg"] == -3.35
    assert logged and logged[0][1] == "level_calibration"
    assert logged[0][0]["inclinometer_calibration"]["zero_offset_deg"] == 1.45


@pytest.mark.parametrize("sources", [("command_line", "saved"), ("saved", "command_line")])
def test_calibration_is_refused_while_a_startup_flag_controls_an_axis(
    monkeypatch, calibration_path, sources
):
    sensor = FakeCalibratingInclinometer()
    _install(monkeypatch, sensor, sources=sources)

    response = _post("/api/inclinometer/level-calibration", {"apply": True})

    assert response.status_code == 409
    assert response.get_json()["error"] == "command_line"
    assert "--inclinometer" in response.get_json()["message"]
    assert not calibration_path.exists()
    assert sensor.applied == []


@pytest.mark.parametrize("status", ["moving", "settling", "sensor_error"])
def test_calibration_waits_for_a_still_reading(monkeypatch, calibration_path, status):
    sensor = FakeCalibratingInclinometer(status=status)
    _install(monkeypatch, sensor)

    response = _post("/api/inclinometer/level-calibration", {"apply": True})

    assert response.status_code == 409
    assert response.get_json()["error"] == status
    assert not calibration_path.exists()


def test_calibration_rejects_an_implausible_offset(monkeypatch, calibration_path):
    reading = LevelReading(
        raw_pitch_deg=-14.0,
        raw_roll_deg=0.0,
        pitch_std_deg=0.05,
        roll_std_deg=0.05,
        snapshot_count=30,
    )
    sensor = FakeCalibratingInclinometer(reading=reading)
    _install(monkeypatch, sensor)

    response = _post("/api/inclinometer/level-calibration", {"apply": True})

    assert response.status_code == 422
    assert response.get_json()["error"] == "out_of_range"
    assert "level floor" in response.get_json()["message"]
    assert not calibration_path.exists()
    assert sensor.applied == []


def test_calibration_that_cannot_be_saved_is_not_applied(monkeypatch, calibration_path):
    sensor = FakeCalibratingInclinometer()
    _install(monkeypatch, sensor)

    def fail(*_args, **_kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr(server, "save_level_calibration", fail)

    response = _post("/api/inclinometer/level-calibration", {"apply": True})

    assert response.status_code == 500
    assert "read-only" in response.get_json()["message"]
    assert sensor.applied == []
    assert server.inclinometer_runtime_config["zero_offset_deg"] == 1.663


@pytest.mark.parametrize("body", [{"apply": "yes"}, {"apply": 1}, {}])
def test_calibration_requires_an_explicit_boolean_apply(monkeypatch, calibration_path, body):
    sensor = FakeCalibratingInclinometer()
    _install(monkeypatch, sensor)

    response = _post("/api/inclinometer/level-calibration", body)

    assert response.status_code == 400
    assert sensor.applied == []


# -- POST /api/inclinometer/level-calibration/undo


def test_undo_restores_the_previous_offsets(monkeypatch, calibration_path):
    sensor = FakeCalibratingInclinometer()
    _install(monkeypatch, sensor)
    _post("/api/inclinometer/level-calibration", {"apply": True})

    response = _post("/api/inclinometer/level-calibration/undo")

    assert response.status_code == 200
    assert sensor.applied[-1] == (1.663, -3.05)
    saved = load_level_calibration(calibration_path)
    assert (saved.zero_offset_deg, saved.method) == (1.663, "undo")
    assert server.inclinometer_runtime_config["zero_offset_deg"] == 1.663


def test_undo_without_a_previous_calibration_is_refused(monkeypatch, calibration_path):
    sensor = FakeCalibratingInclinometer()
    _install(monkeypatch, sensor, saved=None)

    response = _post("/api/inclinometer/level-calibration/undo")

    assert response.status_code == 409
    assert response.get_json()["error"] == "nothing_to_undo"
    assert sensor.applied == []


def test_undo_is_refused_while_a_startup_flag_controls_an_axis(monkeypatch, calibration_path):
    sensor = FakeCalibratingInclinometer()
    _install(monkeypatch, sensor, sources=("command_line", "command_line"))

    response = _post("/api/inclinometer/level-calibration/undo")

    assert response.status_code == 409
    assert response.get_json()["error"] == "command_line"


def test_undo_is_404_without_an_inclinometer(monkeypatch, calibration_path):
    monkeypatch.setattr(server, "inclinometer_service", None)

    assert _post("/api/inclinometer/level-calibration/undo").status_code == 404


# -- GET /api/inclinometer/level reports where the offsets came from


def test_level_reports_calibration_source_and_whether_the_button_can_act(
    monkeypatch, calibration_path
):
    saved = LevelCalibration.from_values(
        zero_offset_deg=1.663, roll_zero_offset_deg=-3.05, calibrated_at="2026-11-05T22:30:00"
    )
    _install(monkeypatch, FakeCalibratingInclinometer(), saved=saved)

    body = server.app.test_client().get("/api/inclinometer/level").get_json()

    assert body["calibration"] == {
        "pitch_source": "saved",
        "roll_source": "saved",
        "calibrated_at": "2026-11-05T22:30:00",
        "can_calibrate": True,
        "can_undo": False,
    }


def test_level_reports_flag_control_disables_calibration(monkeypatch, calibration_path):
    _install(monkeypatch, FakeCalibratingInclinometer(), sources=("command_line", "default"))

    body = server.app.test_client().get("/api/inclinometer/level").get_json()

    assert body["calibration"]["can_calibrate"] is False
    assert body["calibration"]["pitch_source"] == "command_line"
    assert body["calibration"]["calibrated_at"] is None
