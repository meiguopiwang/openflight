/** Live enclosure tilt shown on the Camera tab while setting up the unit. */

/** Sideways lean the app does not correct for; beyond this the readout warns. */
export const LEVEL_LEAN_TOLERANCE_DEG = 1.0;

export type LevelStatus = 'stable' | 'moving' | 'stale' | 'no_stable_preimpact_reading' | 'sensor_error';

export type OffsetSource = 'command_line' | 'saved' | 'default';

/** Where the zero offsets came from and which calibration actions are allowed. */
export interface LevelCalibrationStatus {
  pitch_source: OffsetSource | null;
  roll_source: OffsetSource | null;
  calibrated_at: string | null;
  /** False while startup flags set an offset: flags override a screen calibration. */
  can_calibrate: boolean;
  can_undo: boolean;
}

/** Body of GET /api/inclinometer/level. */
export interface LevelResponse {
  enabled: boolean;
  status: LevelStatus;
  age_s: number | null;
  /** Forward/back tilt relative to the calibrated zero; positive tilts back. */
  pitch_deg: number | null;
  /** Sideways lean after the roll zero offset; positive when the right side is high. */
  roll_deg: number | null;
  configured_iwr_tilt_deg: number | null;
  /** Radar tilt a shot taken now would use. */
  radar_tilt_deg: number | null;
  error: string | null;
  calibration: LevelCalibrationStatus;
}

export type LevelFetchResult = { kind: 'response'; body: LevelResponse } | { kind: 'unavailable' } | { kind: 'failed' };

export type LevelView =
  | { kind: 'checking' }
  | { kind: 'hidden' }
  | { kind: 'waiting'; message: string }
  | {
      kind: 'reading';
      pitchDeg: number;
      rollDeg: number;
      radarTiltDeg: number | null;
      /** True while showing the last stable angles because the unit is moving. */
      settling: boolean;
      message: string | null;
    };

const HOLD_STILL = 'Hold still…';
const SENSOR_ERROR = 'Tilt sensor error';

/** Advance the readout from one poll of the level endpoint. */
export function nextLevelView(previous: LevelView, result: LevelFetchResult): LevelView {
  if (result.kind === 'unavailable') return { kind: 'hidden' };
  if (result.kind === 'failed') return previous;

  const { body } = result;
  if (body.status === 'sensor_error') return { kind: 'waiting', message: SENSOR_ERROR };
  if (body.status === 'stable' && body.pitch_deg !== null && body.roll_deg !== null) {
    return {
      kind: 'reading',
      pitchDeg: body.pitch_deg,
      rollDeg: body.roll_deg,
      radarTiltDeg: body.radar_tilt_deg,
      settling: false,
      message: null,
    };
  }
  if (previous.kind === 'reading') return { ...previous, settling: true, message: HOLD_STILL };
  return { kind: 'waiting', message: HOLD_STILL };
}

/** One decimal, explicit sign by default, and never "-0.0°". */
export function formatLevelDegrees(value: number | null, { signed = true } = {}): string {
  if (value === null) return '—';
  // Round the magnitude so equal left and right leans read the same.
  const rounded = (Math.sign(value) * Math.round(Math.abs(value) * 10)) / 10;
  if (rounded === 0) return '0.0°';
  const sign = signed && rounded > 0 ? '+' : '';
  return `${sign}${rounded.toFixed(1)}°`;
}

export function isLeanLevel(rollDeg: number): boolean {
  return Math.abs(rollDeg) <= LEVEL_LEAN_TOLERANCE_DEG;
}
