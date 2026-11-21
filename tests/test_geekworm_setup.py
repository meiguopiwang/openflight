"""Tests for the Raspberry Pi Geekworm provisioning script."""

import hashlib
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = PROJECT_ROOT / "scripts" / "battery" / "geekworm" / "setup.sh"
BATTERY_OVERLAY_SOURCE = (
    PROJECT_ROOT / "scripts" / "battery" / "geekworm" / "openflight-max17043.dts"
)
PANEL_PACKAGE = (
    PROJECT_ROOT / "scripts" / "battery" / "packages" / "wfplug-batt_1.3+openflight4_arm64.deb"
)
PANEL_PATCH = (
    PROJECT_ROOT / "scripts" / "battery" / "patches" / "wfplug-batt-capacity-and-power.patch"
)
BATTERY_GUIDE = PROJECT_ROOT / "docs" / "using" / "battery.md"
OPERATOR_GUIDE = PROJECT_ROOT / "docs" / "build" / "battery.md"
MAIN_SETUP_SCRIPT = PROJECT_ROOT / "scripts" / "setup" / "setup.sh"


def _run_function(function: str, config_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; "$2" "$3"',
            "geekworm-test",
            str(SETUP_SCRIPT),
            function,
            str(config_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_setup_script_has_valid_bash_syntax():
    subprocess.run(["bash", "-n", SETUP_SCRIPT], check=True)


def test_boot_configuration_update_is_idempotent(tmp_path):
    config = tmp_path / "config.txt"
    config.write_text("[cm5]\nfoo=bar\n", encoding="ascii")

    first = _run_function("update_boot_config", config)
    first_content = config.read_text(encoding="ascii")
    second = _run_function("update_boot_config", config)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert config.read_text(encoding="ascii") == first_content
    assert first_content.count("dtparam=i2c_arm=on") == 1
    assert first_content.count("dtoverlay=openflight-max17043") == 1
    assert "i2c-sensor,max17040" not in first_content
    assert first_content.count("dtoverlay=gpio-charger,gpio=6") == 1
    assert "\n[all]\n# OpenFlight Geekworm" in first_content


def test_boot_configuration_accepts_existing_openflight_settings(tmp_path):
    config = tmp_path / "config.txt"
    original = """\
dtparam=i2c_arm=on
[all]
dtoverlay=openflight-max17043
dtoverlay=gpio-charger,gpio=6,active_low=0,gpio_pull=down,type=mains
"""
    config.write_text(original, encoding="ascii")

    result = _run_function("update_boot_config", config)

    assert result.returncode == 0, result.stderr
    assert config.read_text(encoding="ascii") == original


def test_boot_configuration_replaces_the_resetting_max17040_overlay_in_place(tmp_path):
    # The kernel resets a "maxim,max17040" gauge on every boot, so the charge
    # estimate restarts from the loaded or charging voltage.
    config = tmp_path / "config.txt"
    config.write_text(
        """\
dtparam=i2c_arm=on
[all]
# OpenFlight Geekworm X1202/X1206 telemetry
dtoverlay=i2c-sensor,max17040
dtoverlay=gpio-charger,gpio=6,active_low=0,gpio_pull=down,type=mains
""",
        encoding="ascii",
    )

    first = _run_function("update_boot_config", config)
    content = config.read_text(encoding="ascii")
    second = _run_function("update_boot_config", config)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert config.read_text(encoding="ascii") == content
    assert (
        content
        == """\
dtparam=i2c_arm=on
[all]
# OpenFlight Geekworm X1202/X1206 telemetry
dtoverlay=openflight-max17043
dtoverlay=gpio-charger,gpio=6,active_low=0,gpio_pull=down,type=mains
"""
    )


def test_boot_configuration_drops_a_duplicate_max17040_overlay(tmp_path):
    config = tmp_path / "config.txt"
    config.write_text(
        "dtparam=i2c_arm=on\n"
        "dtoverlay=openflight-max17043\n"
        "dtoverlay=i2c-sensor,max17040\n"
        "dtoverlay=gpio-charger,gpio=6,active_low=0,gpio_pull=down,type=mains\n",
        encoding="ascii",
    )

    result = _run_function("update_boot_config", config)
    content = config.read_text(encoding="ascii")

    assert result.returncode == 0, result.stderr
    assert content.count("dtoverlay=openflight-max17043") == 1
    assert "i2c-sensor,max17040" not in content


def test_boot_configuration_leaves_other_i2c_sensor_overlays_alone(tmp_path):
    config = tmp_path / "config.txt"
    config.write_text("dtoverlay=i2c-sensor,bme280\n", encoding="ascii")

    result = _run_function("update_boot_config", config)
    content = config.read_text(encoding="ascii")

    assert result.returncode == 0, result.stderr
    assert "dtoverlay=i2c-sensor,bme280\n" in content
    assert content.count("dtoverlay=openflight-max17043") == 1


def test_battery_overlay_source_binds_a_non_resetting_max17043_at_0x36():
    source = BATTERY_OVERLAY_SOURCE.read_text(encoding="ascii")

    assert "/plugin/;" in source
    assert "target = <&i2c_arm>;" in source
    assert 'compatible = "maxim,max17043";' in source
    assert "reg = <0x36>;" in source
    assert '"maxim,max17040"' not in source


def _fake_dtc(tmp_path: Path) -> Path:
    """A dtc stand-in that records its arguments and writes the output file."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    dtc = bin_dir / "dtc"
    dtc.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$@" > "$FAKE_DTC_ARGS"\n'
        'while (( $# )); do [[ "$1" == -o ]] && out="$2"; shift; done\n'
        'printf compiled > "$out"\n',
        encoding="ascii",
    )
    dtc.chmod(0o755)
    return bin_dir


def _run_install_overlay(tmp_path: Path, overlays_dir: Path) -> subprocess.CompletedProcess[str]:
    bin_dir = _fake_dtc(tmp_path)
    return subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; as_root() { "$@"; }; install_battery_overlay; '
            'echo "REBOOT_REQUIRED=$REBOOT_REQUIRED"',
            "geekworm-test",
            str(SETUP_SCRIPT),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "FAKE_DTC_ARGS": str(tmp_path / "dtc-args"),
            "OPENFLIGHT_GEEKWORM_OVERLAYS_DIR": str(overlays_dir),
        },
    )


def test_install_battery_overlay_compiles_the_source_into_the_overlays_dir(tmp_path):
    overlays = tmp_path / "overlays"
    overlays.mkdir()

    result = _run_install_overlay(tmp_path, overlays)

    assert result.returncode == 0, result.stderr
    assert (overlays / "openflight-max17043.dtbo").read_text() == "compiled"
    args = (tmp_path / "dtc-args").read_text().split()
    assert args[:4] == ["-@", "-I", "dts", "-O"]
    assert str(BATTERY_OVERLAY_SOURCE) in args
    assert "REBOOT_REQUIRED=true" in result.stdout


def test_install_battery_overlay_is_idempotent(tmp_path):
    overlays = tmp_path / "overlays"
    overlays.mkdir()
    _run_install_overlay(tmp_path, overlays)

    result = _run_install_overlay(tmp_path, overlays)

    assert result.returncode == 0, result.stderr
    assert "already installed" in result.stdout
    assert "REBOOT_REQUIRED=false" in result.stdout


def test_install_battery_overlay_fails_without_an_overlays_dir(tmp_path):
    result = _run_install_overlay(tmp_path, tmp_path / "missing")

    assert result.returncode != 0
    assert "overlays directory" in result.stderr


def test_boot_configuration_rejects_conflicting_charger_overlay(tmp_path):
    config = tmp_path / "config.txt"
    config.write_text(
        "dtoverlay=gpio-charger,gpio=7,active_low=1\n",
        encoding="ascii",
    )

    result = _run_function("update_boot_config", config)

    assert result.returncode != 0
    assert "different gpio-charger overlay" in result.stderr


def test_eeprom_configuration_replaces_and_deduplicates_power_settings(tmp_path):
    config = tmp_path / "eeprom.conf"
    config.write_text(
        "BOOT_UART=1\nPSU_MAX_CURRENT=3000\nPOWER_OFF_ON_HALT=0\nPSU_MAX_CURRENT=2000\n",
        encoding="ascii",
    )

    result = _run_function("update_eeprom_config", config)
    content = config.read_text(encoding="ascii")

    assert result.returncode == 0, result.stderr
    assert "BOOT_UART=1" in content
    assert content.count("PSU_MAX_CURRENT=5000") == 1
    assert content.count("POWER_OFF_ON_HALT=1") == 1
    assert "PSU_MAX_CURRENT=3000" not in content
    assert "POWER_OFF_ON_HALT=0" not in content


def test_bundled_panel_package_matches_setup_checksum():
    digest = hashlib.sha256(PANEL_PACKAGE.read_bytes()).hexdigest()

    assert digest == "55db8a460f99758f2dac9d509b29907e0e268ee88bbff4edb6adcee312046d5c"


def test_panel_patch_uses_external_power_for_charge_icon():
    patch = PANEL_PATCH.read_text(encoding="utf-8")

    assert "power_supply_on_external_power" in patch
    assert '"online"' in patch
    assert '"type"' in patch
    assert 'g_ascii_strcasecmp(type, "Battery")' in patch
    assert "external_power == 0" in patch
    assert "STAT_DISCHARGING" in patch


def test_operator_guide_links_models_and_distinguishes_batteries():
    guide = OPERATOR_GUIDE.read_text(encoding="utf-8")

    assert "https://geekworm.com/products/x1202" in guide
    assert "https://geekworm.com/products/x1206" in guide
    assert "Four 3.7V 18650 cells" in guide
    assert "Four 3.7V 21700 cells" in guide
    assert "X1206 V1.1" in guide
    assert "X1206 V2.0" in guide


def test_battery_guide_documents_provider_interface_and_cli():
    guide = BATTERY_GUIDE.read_text(encoding="utf-8")

    assert "--battery geekworm" in guide
    assert "PowerReader" in guide
    # The operator guide lives at docs/build/battery.md; this asserts the
    # provider overview still links to it.
    assert "../build/battery.md" in guide


def test_battery_guides_warn_against_charging_below_freezing():
    for guide_path in (BATTERY_GUIDE, OPERATOR_GUIDE):
        guide = guide_path.read_text(encoding="utf-8")

        assert "Do not charge" in guide
        assert "below 0 °C (32 °F)" in guide


def test_main_setup_offers_geekworm_provisioning():
    setup = MAIN_SETUP_SCRIPT.read_text(encoding="utf-8")

    assert 'confirm "Do you have a Geekworm X1202 or X1206 UPS to set up?"' in setup
    assert '"$PROJECT_DIR/scripts/battery/geekworm/setup.sh"' in setup


def _ups_setup_block() -> str:
    """The UPS step of scripts/setup/setup.sh, from its marker to the next step."""
    setup = MAIN_SETUP_SCRIPT.read_text(encoding="utf-8")
    start = setup.index("# --- Geekworm X1202/X1206 power telemetry ---")
    end = setup.index("# --- Bluetooth", start)
    return setup[start:end]


def _run_ups_step(
    tmp_path: Path, answers: list[str], geekworm_exit: int = 0, guard_exit: int = 0
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Run the UPS step under set -e with stubbed scripts and scripted answers."""
    calls = tmp_path / "calls.log"
    battery_dir = tmp_path / "scripts" / "battery"
    (battery_dir / "geekworm").mkdir(parents=True)
    stubs = {
        battery_dir / "geekworm" / "setup.sh": ("geekworm", geekworm_exit),
        battery_dir / "install_battery_guard.sh": ("guard", guard_exit),
    }
    for path, (name, exit_code) in stubs.items():
        path.write_text(
            f'#!/bin/bash\necho {name} >> "{calls.as_posix()}"\nexit {exit_code}\n',
            encoding="ascii",
        )
        path.chmod(0o755)

    harness = f"""\
set -e
PROJECT_DIR="{tmp_path.as_posix()}"
ANSWERS=({" ".join(answers)})
confirm() {{
    local answer="${{ANSWERS[0]}}"
    ANSWERS=("${{ANSWERS[@]:1}}")
    echo "asked: $1 -> $answer"
    [[ "$answer" == "y" ]]
}}
info() {{ echo "info: $1"; }}
warn() {{ echo "warn: $1"; }}
{_ups_setup_block()}
echo "setup continued"
"""
    result = subprocess.run(["bash", "-c", harness], check=False, capture_output=True, text=True)
    logged = calls.read_text(encoding="ascii").split() if calls.exists() else []
    return result, logged


def test_ups_step_installs_low_battery_shutdown_when_accepted(tmp_path):
    result, calls = _run_ups_step(tmp_path, ["y", "y"])

    assert result.returncode == 0, result.stderr
    assert calls == ["geekworm", "guard"]
    assert "Power the Pi off automatically when the UPS battery runs low?" in result.stdout
    assert "setup continued" in result.stdout


def test_ups_step_skips_low_battery_shutdown_when_declined(tmp_path):
    result, calls = _run_ups_step(tmp_path, ["y", "n"])

    assert result.returncode == 0, result.stderr
    assert calls == ["geekworm"]
    assert "Run later with: ./scripts/battery/install_battery_guard.sh" in result.stdout


def test_ups_step_asks_nothing_more_without_a_ups(tmp_path):
    result, calls = _run_ups_step(tmp_path, ["n"])

    assert result.returncode == 0, result.stderr
    assert not calls
    assert "runs low" not in result.stdout


def test_ups_step_still_offers_shutdown_when_geekworm_setup_fails(tmp_path):
    # A failed taskbar package (issue #318) must not end the run or skip the guard.
    result, calls = _run_ups_step(tmp_path, ["y", "y"], geekworm_exit=1)

    assert result.returncode == 0, result.stderr
    assert calls == ["geekworm", "guard"]
    assert "warn: Geekworm setup did not finish." in result.stdout
    assert "Reboot before verifying" not in result.stdout
    assert "setup continued" in result.stdout


def test_ups_step_warns_and_continues_when_guard_install_fails(tmp_path):
    result, calls = _run_ups_step(tmp_path, ["y", "y"], guard_exit=1)

    assert result.returncode == 0, result.stderr
    assert calls == ["geekworm", "guard"]
    assert "warn: Low-battery shutdown install failed." in result.stdout
    assert "setup continued" in result.stdout


def test_ups_step_defaults_low_battery_shutdown_to_yes():
    block = _ups_setup_block()

    assert 'battery runs low? (the cells are unprotected)" "Y"' in block
