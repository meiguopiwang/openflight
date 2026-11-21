import { describe, expect, it } from 'vitest';
import {
  formatLevelDegrees,
  isLeanLevel,
  LEVEL_LEAN_TOLERANCE_DEG,
  nextLevelView,
  type LevelResponse,
  type LevelView,
} from './levelReadout';

const stable: LevelResponse = {
  enabled: true,
  status: 'stable',
  age_s: 0.1,
  pitch_deg: -0.03,
  roll_deg: 4.07,
  configured_iwr_tilt_deg: 9.4,
  radar_tilt_deg: 9.37,
  error: null,
  calibration: {
    pitch_source: 'saved',
    roll_source: 'saved',
    calibrated_at: '2026-11-05T22:40:00',
    can_calibrate: true,
    can_undo: false,
  },
};

const reading: LevelView = {
  kind: 'reading',
  pitchDeg: -0.03,
  rollDeg: 4.07,
  radarTiltDeg: 9.37,
  settling: false,
  message: null,
};

describe('formatLevelDegrees', () => {
  it('shows one decimal with an explicit sign', () => {
    expect(formatLevelDegrees(4.07)).toBe('+4.1°');
    expect(formatLevelDegrees(-1.25)).toBe('-1.3°');
  });

  it('rounds equal positive and negative angles to the same magnitude', () => {
    expect(formatLevelDegrees(1.25)).toBe('+1.3°');
    expect(formatLevelDegrees(-1.25)).toBe('-1.3°');
  });

  it('never shows a negative zero', () => {
    expect(formatLevelDegrees(-0.03)).toBe('0.0°');
    expect(formatLevelDegrees(0.04)).toBe('0.0°');
    expect(formatLevelDegrees(0)).toBe('0.0°');
  });

  it('shows a dash for a missing angle', () => {
    expect(formatLevelDegrees(null)).toBe('—');
  });

  it('can omit the sign for unsigned values', () => {
    expect(formatLevelDegrees(9.37, { signed: false })).toBe('9.4°');
  });
});

describe('isLeanLevel', () => {
  it('accepts lean within the tolerance on either side', () => {
    expect(isLeanLevel(LEVEL_LEAN_TOLERANCE_DEG)).toBe(true);
    expect(isLeanLevel(-LEVEL_LEAN_TOLERANCE_DEG)).toBe(true);
    expect(isLeanLevel(0)).toBe(true);
  });

  it('flags lean beyond the tolerance', () => {
    expect(isLeanLevel(4.07)).toBe(false);
    expect(isLeanLevel(-1.2)).toBe(false);
  });
});

describe('nextLevelView', () => {
  it('starts by checking and hides when the server has no inclinometer', () => {
    expect(nextLevelView({ kind: 'checking' }, { kind: 'unavailable' })).toEqual({ kind: 'hidden' });
  });

  it('shows the angles from a stable reading', () => {
    expect(nextLevelView({ kind: 'checking' }, { kind: 'response', body: stable })).toEqual(reading);
  });

  it('keeps the last angles but marks them settling while the unit moves', () => {
    const moving = { ...stable, status: 'moving' as const, pitch_deg: null, roll_deg: null, radar_tilt_deg: null };

    expect(nextLevelView(reading, { kind: 'response', body: moving })).toEqual({
      ...reading,
      settling: true,
      message: 'Hold still…',
    });
  });

  it('waits with a message when there has never been a stable reading', () => {
    const stale = { ...stable, status: 'no_stable_preimpact_reading' as const, pitch_deg: null, roll_deg: null };

    expect(nextLevelView({ kind: 'checking' }, { kind: 'response', body: stale })).toEqual({
      kind: 'waiting',
      message: 'Hold still…',
    });
  });

  it('reports a sensor error instead of stale angles', () => {
    const failed = {
      ...stable,
      status: 'sensor_error' as const,
      pitch_deg: null,
      roll_deg: null,
      radar_tilt_deg: null,
      error: 'I2C read failed',
    };

    expect(nextLevelView(reading, { kind: 'response', body: failed })).toEqual({
      kind: 'waiting',
      message: 'Tilt sensor error',
    });
  });

  it('keeps showing the last view through a transient network failure', () => {
    expect(nextLevelView(reading, { kind: 'failed' })).toBe(reading);
    expect(nextLevelView({ kind: 'checking' }, { kind: 'failed' })).toEqual({ kind: 'checking' });
  });

  it('reappears when an inclinometer later responds', () => {
    expect(nextLevelView({ kind: 'hidden' }, { kind: 'response', body: stable })).toEqual(reading);
  });

  it('treats a stable status without angles as waiting rather than showing blanks', () => {
    const blank = { ...stable, pitch_deg: null, roll_deg: null };

    expect(nextLevelView({ kind: 'checking' }, { kind: 'response', body: blank })).toEqual({
      kind: 'waiting',
      message: 'Hold still…',
    });
  });

  it('keeps radar tilt optional when no IWR6843 is configured', () => {
    const noRadar = { ...stable, configured_iwr_tilt_deg: null, radar_tilt_deg: null };

    expect(nextLevelView({ kind: 'checking' }, { kind: 'response', body: noRadar })).toEqual({
      ...reading,
      radarTiltDeg: null,
    });
  });
});
