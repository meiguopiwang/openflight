"""Tests for deterministic high-speed camera auto exposure."""

import numpy as np
import pytest

from openflight.camera.auto_exposure import (
    EXPOSURE_STEPS,
    AutoExposurePolicy,
    ExposureObservation,
    exposure_steps_for_fps,
    measure_exposure,
    motion_blur_risk,
)


def observation(status, recommendation, *, median=50.0, p90=100.0):
    """Build one deterministic policy observation."""
    return ExposureObservation(
        sample_available=True,
        status=status,
        recommendation=recommendation,
        message=status,
        p10=10.0,
        median=median,
        p90=p90,
        contrast=p90 - 10.0,
        clipped_pct=0.0,
        dark_pct=0.0,
    )


def test_exposure_ladder_is_monotonic_and_respects_frame_period():
    assert [step.signal for step in EXPOSURE_STEPS] == sorted(
        step.signal for step in EXPOSURE_STEPS
    )
    assert exposure_steps_for_fps(488.0) == EXPOSURE_STEPS
    assert max(step.exposure_us for step in exposure_steps_for_fps(1000.0)) < 1000
    with pytest.raises(ValueError, match="positive"):
        exposure_steps_for_fps(0)


def test_fully_clipped_view_at_100us_x2_can_still_step_darker():
    """Replay the 2026-10-18 range session: 100us x2 left ~91% of pixels white.

    That was the darkest validated step, so the policy locked on "overexposed"
    for 99 shots. Sunlit ranges need steps below it.
    """
    policy = AutoExposurePolicy(fps=450.0)

    decision = policy.evaluate(
        observation("too_bright", "darker", median=255.0, p90=255.0),
        exposure_us=100,
        gain=2.0,
    )

    assert decision.status == "adjusting"
    assert decision.target.signal < 100 * 2.0


def test_ladder_reaches_bright_sun_with_unity_gain():
    darkest = EXPOSURE_STEPS[0]

    # At least 8x darker than the old 100us x2 floor, without any analogue
    # boost, and still at least two sensor rows (~7.3us each at 320x200).
    assert darkest.signal <= (100 * 2.0) / 8
    assert darkest.gain == 1.0
    assert darkest.exposure_us >= 15


def test_ladder_gains_fit_the_sensor_gain_range():
    """The OV9281 gain register tops out at 255/16 = 15.94x.

    Saved 2026-10-24 captures that requested 1000us x20 recorded 15.94x on
    every frame, so steps above it were silently clamped and the policy's
    brightness model no longer matched the image.
    """
    sensor_max_gain = 255 / 16

    assert all(1.0 <= step.gain <= sensor_max_gain for step in EXPOSURE_STEPS)


def test_ladder_signal_stays_strictly_increasing():
    """Equal-brightness steps (e.g. 1000us x20 vs 1250us x16) waste a check."""
    signals = [step.signal for step in EXPOSURE_STEPS]

    assert all(lower < upper for lower, upper in zip(signals, signals[1:]))


def test_ladder_steps_are_distinct_after_sensor_row_rounding():
    """Exposure is applied in whole sensor rows, so steps must not collapse."""
    row_us = (320 + 1136) / 200.0  # 320x200 line length / 200 MHz pixel rate
    rows = [(int(step.exposure_us // row_us), step.gain) for step in EXPOSURE_STEPS]

    assert len(set(rows)) == len(rows)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(18, "too_dark"), (110, "good"), (252, "too_bright")],
)
def test_measure_exposure_classifies_impact_zone(value, expected):
    image = np.full((200, 320), value, dtype=np.uint8)
    if expected == "good":
        image[100:175, 90:230] = np.tile(
            np.linspace(45, 185, 140, dtype=np.uint8),
            (75, 1),
        )

    result = measure_exposure(image)

    assert result.status == expected
    assert result.sample_available is True


def test_measure_exposure_flags_nearly_black_view():
    result = measure_exposure(np.zeros((200, 320), dtype=np.uint8))

    assert result.status == "too_dark"
    assert "lens cover" in result.message


def test_startup_dark_scene_jumps_more_than_one_step():
    policy = AutoExposurePolicy(fps=488.0)

    decision = policy.evaluate(
        observation("too_dark", "brighter", median=18.0, p90=40.0),
        exposure_us=250,
        gain=4.0,
    )

    assert decision.status == "adjusting"
    assert decision.target is not None
    assert decision.target.signal > 300 * 5.0
    assert decision.analysis_eligible is False


def test_startup_bright_scene_jumps_darker():
    policy = AutoExposurePolicy(fps=488.0)

    decision = policy.evaluate(
        observation("too_bright", "darker", median=240.0, p90=255.0),
        exposure_us=800,
        gain=18.0,
    )

    assert decision.target is not None
    assert decision.target.signal < 800 * 18


def test_acceptable_startup_observation_marks_analysis_ready():
    policy = AutoExposurePolicy(fps=488.0)

    decision = policy.evaluate(
        observation("good", "hold", median=100.0),
        exposure_us=500,
        gain=12.0,
    )

    assert decision.status == "ready"
    assert decision.analysis_eligible is True
    assert not decision.should_apply


def test_ready_setting_stays_locked_until_the_next_startup():
    policy = AutoExposurePolicy(fps=488.0)
    ready = policy.evaluate(
        observation("good", "hold"),
        exposure_us=500,
        gain=12.0,
    )

    changed_scene = policy.evaluate(
        observation("too_dark", "brighter", median=18.0, p90=40.0),
        exposure_us=500,
        gain=12.0,
    )
    policy.reset()
    next_startup = policy.evaluate(
        observation("too_dark", "brighter", median=18.0, p90=40.0),
        exposure_us=500,
        gain=12.0,
    )

    assert changed_scene is ready
    assert changed_scene.status == "ready"
    assert not changed_scene.should_apply
    assert next_startup.status == "adjusting"
    assert next_startup.should_apply
    assert policy.startup is True


def test_ladder_limit_stays_locked_until_the_next_startup():
    policy = AutoExposurePolicy(fps=488.0)
    darkest = EXPOSURE_STEPS[-1]

    failed = policy.evaluate(
        observation("too_dark", "brighter", median=10.0, p90=20.0),
        exposure_us=darkest.exposure_us,
        gain=darkest.gain,
    )
    locked = policy.evaluate(
        observation("marginal", "brighter", median=40.0, p90=95.0),
        exposure_us=darkest.exposure_us,
        gain=darkest.gain,
    )
    policy.reset()
    recovered = policy.evaluate(
        observation("marginal", "brighter", median=40.0, p90=95.0),
        exposure_us=darkest.exposure_us,
        gain=darkest.gain,
    )

    assert failed.status == "lighting_required"
    assert failed.analysis_eligible is False
    assert "add or redirect light" in failed.message
    assert locked is failed
    assert recovered.status == "ready"
    assert recovered.analysis_eligible is True


def test_partly_clipped_sunny_startup_keeps_stepping_darker_while_steps_remain():
    """Replay the 2026-11-01 outdoor boot that locked with darker steps untried.

    Starting from the saved "Evening" seed, a sunlit view with a mid-grey
    median but ~17% clipped pixels only moves one step per check. The policy
    must not give up while darker validated steps are still available.
    """
    policy = AutoExposurePolicy(fps=450.0)
    sunny = observation("too_bright", "darker", median=96.0, p90=255.0)
    exposure_us, gain = 450, 10.0
    visited = [(exposure_us, gain)]

    decision = policy.evaluate(sunny, exposure_us=exposure_us, gain=gain)
    while decision.should_apply:
        exposure_us, gain = decision.target.exposure_us, decision.target.gain
        visited.append((exposure_us, gain))
        decision = policy.evaluate(sunny, exposure_us=exposure_us, gain=gain)

    darkest = EXPOSURE_STEPS[0]
    assert visited[-1] == (darkest.exposure_us, darkest.gain)
    assert decision.status == "lighting_required"
    assert "overexposed" in decision.message


def test_startup_settles_on_the_first_acceptable_step_after_several_adjustments():
    policy = AutoExposurePolicy(fps=450.0)
    sunny = observation("too_bright", "darker", median=96.0, p90=255.0)
    exposure_us, gain = 450, 10.0
    for _ in range(4):
        decision = policy.evaluate(sunny, exposure_us=exposure_us, gain=gain)
        assert decision.status == "adjusting"
        exposure_us, gain = decision.target.exposure_us, decision.target.gain

    ready = policy.evaluate(
        observation("good", "hold", median=100.0),
        exposure_us=exposure_us,
        gain=gain,
    )

    assert ready.status == "ready"
    assert ready.analysis_eligible is True


def test_startup_never_returns_to_a_step_it_already_rejected():
    """Overshooting past a too-bright step must not bounce back to it forever."""
    policy = AutoExposurePolicy(fps=450.0)
    too_bright = policy.evaluate(
        observation("too_bright", "darker", median=200.0, p90=255.0),
        exposure_us=350,
        gain=6.0,
    )
    darker = too_bright.target

    failed = policy.evaluate(
        observation("too_dark", "brighter", median=30.0, p90=60.0),
        exposure_us=darker.exposure_us,
        gain=darker.gain,
    )
    seen = {(350, 6.0), (darker.exposure_us, darker.gain)}
    while failed.should_apply:
        target = (failed.target.exposure_us, failed.target.gain)
        assert target not in seen
        seen.add(target)
        failed = policy.evaluate(
            observation("too_bright", "darker", median=200.0, p90=255.0)
            if target[0] * target[1] >= 350 * 6.0
            else observation("too_dark", "brighter", median=30.0, p90=60.0),
            exposure_us=target[0],
            gain=target[1],
        )

    assert failed.status == "lighting_required"
    assert failed.analysis_eligible is False


def test_startup_overshoot_tries_the_untried_step_in_between():
    policy = AutoExposurePolicy(fps=450.0)
    darker = policy.evaluate(
        observation("too_bright", "darker", median=200.0, p90=255.0),
        exposure_us=350,
        gain=6.0,
    ).target
    assert (darker.exposure_us, darker.gain) == (250, 4.0)

    between = policy.evaluate(
        observation("too_dark", "brighter", median=30.0, p90=60.0),
        exposure_us=darker.exposure_us,
        gain=darker.gain,
    ).target
    ready = policy.evaluate(
        observation("good", "hold", median=100.0),
        exposure_us=between.exposure_us,
        gain=between.gain,
    )

    assert (between.exposure_us, between.gain) == (300, 5.0)
    assert ready.status == "ready"


def _run_policy(policy, start, rate):
    """Drive the policy until it locks; ``rate(step)`` returns each observation."""
    exposure_us, gain = start
    visited = [start]
    decision = policy.evaluate(rate((exposure_us, gain)), exposure_us=exposure_us, gain=gain)
    while decision.should_apply:
        exposure_us, gain = decision.target.exposure_us, decision.target.gain
        visited.append((exposure_us, gain))
        decision = policy.evaluate(rate((exposure_us, gain)), exposure_us=exposure_us, gain=gain)
    return decision, visited


def test_usable_setting_tries_the_suggested_neighbor_and_locks_good():
    """Replay the 2026-11-01 recalibration that stopped at "usable".

    500us x15 measured median 61 / p90 98 (two short of "good") and suggested
    a brighter setting, but the policy locked without trying 650us x15.
    """
    policy = AutoExposurePolicy(fps=450.0)
    ratings = {
        (500, 15.0): observation("marginal", "brighter", median=61.0, p90=98.0),
        (650, 15.0): observation("good", "hold", median=80.0, p90=128.0),
    }

    decision, visited = _run_policy(policy, (500, 15.0), ratings.__getitem__)

    assert visited == [(500, 15.0), (650, 15.0)]
    assert decision.status == "ready"
    assert decision.observation.status == "good"


def test_usable_setting_keeps_moving_while_neighbors_stay_usable():
    policy = AutoExposurePolicy(fps=450.0)
    ratings = {
        (500, 12.0): observation("marginal", "brighter", median=50.0, p90=90.0),
        (500, 15.0): observation("marginal", "brighter", median=58.0, p90=96.0),
        (650, 15.0): observation("good", "hold", median=80.0, p90=128.0),
    }

    decision, visited = _run_policy(policy, (500, 12.0), ratings.__getitem__)

    assert visited == [(500, 12.0), (500, 15.0), (650, 15.0)]
    assert decision.observation.status == "good"


def test_usable_setting_is_restored_when_the_neighbor_is_worse():
    policy = AutoExposurePolicy(fps=450.0)
    ratings = {
        (500, 15.0): observation("marginal", "brighter", median=170.0, p90=200.0),
        (650, 15.0): observation("too_bright", "darker", median=230.0, p90=255.0),
    }

    decision, visited = _run_policy(policy, (500, 15.0), ratings.__getitem__)

    assert visited == [(500, 15.0), (650, 15.0), (500, 15.0)]
    assert decision.status == "ready"
    assert decision.analysis_eligible is True
    assert decision.observation.status == "marginal"


def test_usable_setting_locks_when_the_neighbor_points_back():
    """Two usable neighbors recommending each other must not ping-pong."""
    policy = AutoExposurePolicy(fps=450.0)
    ratings = {
        (500, 15.0): observation("marginal", "brighter", median=60.0, p90=97.0),
        (650, 15.0): observation("marginal", "darker", median=185.0, p90=210.0),
    }

    decision, visited = _run_policy(policy, (500, 15.0), ratings.__getitem__)

    assert visited == [(500, 15.0), (650, 15.0)]
    assert decision.status == "ready"
    assert decision.observation.status == "marginal"


def test_usable_setting_at_the_end_of_the_ladder_locks_immediately():
    policy = AutoExposurePolicy(fps=450.0)
    darkest = EXPOSURE_STEPS[0]

    decision = policy.evaluate(
        observation("marginal", "darker", median=190.0, p90=230.0),
        exposure_us=darkest.exposure_us,
        gain=darkest.gain,
    )

    assert decision.status == "ready"
    assert not decision.should_apply


def test_restored_usable_setting_that_is_no_longer_usable_keeps_searching():
    """If the light changes during fine-tuning, fall back to normal stepping."""
    policy = AutoExposurePolicy(fps=450.0)
    ratings = iter(
        [
            observation("marginal", "brighter", median=170.0, p90=200.0),  # 500 x15
            observation("too_bright", "darker", median=230.0, p90=255.0),  # 650 x15
            observation("too_dark", "brighter", median=20.0, p90=40.0),  # back at 500 x15
        ]
    )

    decision, visited = _run_policy(policy, (500, 15.0), lambda _step: next(ratings, None))

    assert visited[:3] == [(500, 15.0), (650, 15.0), (500, 15.0)]
    assert decision.status == "lighting_required"


def test_default_startup_budget_can_walk_the_whole_ladder():
    policy = AutoExposurePolicy(fps=450.0)

    assert policy.startup_max_adjustments == len(policy.steps) - 1


def test_startup_attempt_limit_requires_lighting_change():
    policy = AutoExposurePolicy(fps=488.0, startup_max_adjustments=1)
    dark = observation("too_dark", "brighter", median=18.0, p90=40.0)
    first = policy.evaluate(dark, exposure_us=250, gain=4.0)

    failed = policy.evaluate(
        dark,
        exposure_us=first.target.exposure_us,
        gain=first.target.gain,
    )

    assert failed.status == "lighting_required"
    assert not failed.should_apply


@pytest.mark.parametrize(
    ("exposure_us", "expected"),
    [(500, "low"), (650, "elevated"), (1000, "high")],
)
def test_motion_blur_risk(exposure_us, expected):
    assert motion_blur_risk(exposure_us) == expected
