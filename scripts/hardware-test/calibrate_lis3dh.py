#!/usr/bin/env python3
"""Average a stationary LIS3DH and print its recommended zero-offset flags."""

import argparse
import statistics
import time
from dataclasses import dataclass

from openflight.inclinometer import LIS3DH, AccelerationSample
from openflight.inclinometer.service import pitch_degrees, roll_degrees


@dataclass(frozen=True)
class Calibration:
    """Mean raw angles and the offsets that map them onto the references."""

    raw_pitch: float
    pitch_std: float
    pitch_offset: float
    raw_roll: float
    roll_std: float
    roll_offset: float


def recommend_offsets(
    samples: list[AccelerationSample],
    *,
    reference_pitch: float = 0.0,
    reference_roll: float = 0.0,
) -> Calibration:
    """Offsets so the averaged raw pitch and roll read the measured references."""
    pitches = [pitch_degrees(sample) for sample in samples]
    rolls = [roll_degrees(sample) for sample in samples]
    raw_pitch = statistics.mean(pitches)
    raw_roll = statistics.mean(rolls)
    return Calibration(
        raw_pitch=raw_pitch,
        pitch_std=statistics.pstdev(pitches),
        pitch_offset=reference_pitch - raw_pitch,
        raw_roll=raw_roll,
        roll_std=statistics.pstdev(rolls),
        roll_offset=reference_roll - raw_roll,
    )


def format_report(
    result: Calibration, *, reference_pitch: float, reference_roll: float
) -> list[str]:
    """Lines printed after sampling."""
    return [
        f"Raw pitch mean: {result.raw_pitch:+.3f}deg (std dev {result.pitch_std:.3f}deg)",
        f"Reference pitch: {reference_pitch:+.3f}deg",
        f"Recommended flag: --inclinometer-zero-offset {result.pitch_offset:+.3f}",
        f"Raw roll mean: {result.raw_roll:+.3f}deg (std dev {result.roll_std:.3f}deg)",
        f"Reference roll: {reference_roll:+.3f}deg (positive = right side high)",
        f"Recommended flag: --inclinometer-roll-zero-offset {result.roll_offset:+.3f}",
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bus", type=int, default=1)
    parser.add_argument("--address", type=lambda value: int(value, 0), default=0x18)
    parser.add_argument("--samples", type=int, default=50)
    parser.add_argument("--interval", type=float, default=0.1)
    parser.add_argument(
        "--reference-pitch",
        type=float,
        default=0.0,
        help="Known pitch of the supporting surface in degrees (default: level/0)",
    )
    parser.add_argument(
        "--reference-roll",
        type=float,
        default=0.0,
        help=(
            "Known side-to-side lean in degrees, positive when the right side is high "
            "(standing behind the unit facing the target; default: level/0)"
        ),
    )
    args = parser.parse_args()
    if args.samples < 2:
        parser.error("--samples must be at least 2")

    sensor = LIS3DH(bus_number=args.bus, address=args.address)
    sensor.initialize()
    samples = []
    try:
        print(f"Keep the enclosure still while collecting {args.samples} samples...")
        for _ in range(args.samples):
            samples.append(sensor.read())
            time.sleep(args.interval)
    finally:
        sensor.close()

    result = recommend_offsets(
        samples,
        reference_pitch=args.reference_pitch,
        reference_roll=args.reference_roll,
    )
    for line in format_report(
        result,
        reference_pitch=args.reference_pitch,
        reference_roll=args.reference_roll,
    ):
        print(line)


if __name__ == "__main__":
    main()
