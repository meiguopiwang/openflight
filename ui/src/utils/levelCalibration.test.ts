import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  calibrationSourceLabel,
  launchAngleShiftNote,
  nextCalibrationStep,
  requestLevelCalibration,
  requestLevelCalibrationUndo,
  type CalibrationPreview,
  type CalibrationStep,
} from './levelCalibration';
import type { LevelCalibrationStatus } from './levelReadout';

const preview: CalibrationPreview = {
  applied: false,
  current: { zero_offset_deg: 1.663, roll_zero_offset_deg: -3.05 },
  proposed: { zero_offset_deg: 1.45, roll_zero_offset_deg: -3.35 },
  change: { pitch_deg: -0.213, roll_deg: -0.3 },
  reading: { raw_pitch_deg: -1.45, raw_roll_deg: 3.35, pitch_std_deg: 0.05, roll_std_deg: 0.06, snapshot_count: 30 },
  calibrated_at: '2026-11-05T22:40:00',
};

const status = (overrides: Partial<LevelCalibrationStatus> = {}): LevelCalibrationStatus => ({
  pitch_source: 'saved',
  roll_source: 'saved',
  calibrated_at: '2026-11-05T22:40:00',
  can_calibrate: true,
  can_undo: true,
  ...overrides,
});

describe('nextCalibrationStep', () => {
  it('walks idle → checking → confirm → applying → done', () => {
    let step: CalibrationStep = { kind: 'idle' };
    step = nextCalibrationStep(step, { type: 'start' });
    expect(step).toEqual({ kind: 'checking' });
    step = nextCalibrationStep(step, { type: 'previewed', preview });
    expect(step).toEqual({ kind: 'confirm', preview });
    step = nextCalibrationStep(step, { type: 'confirm' });
    expect(step).toEqual({ kind: 'applying', preview });
    step = nextCalibrationStep(step, { type: 'applied', result: { ...preview, applied: true } });
    expect(step).toEqual({ kind: 'done', result: { ...preview, applied: true } });
  });

  it('undoes from done and returns to idle with a message', () => {
    let step: CalibrationStep = { kind: 'done', result: { ...preview, applied: true } };
    step = nextCalibrationStep(step, { type: 'undo' });
    expect(step).toEqual({ kind: 'undoing' });
    step = nextCalibrationStep(step, { type: 'undone' });
    expect(step).toEqual({ kind: 'idle', notice: 'Previous calibration restored.' });
  });

  it('can undo from idle when an earlier calibration is undoable', () => {
    expect(nextCalibrationStep({ kind: 'idle' }, { type: 'undo' })).toEqual({ kind: 'undoing' });
  });

  it('shows the server message on failure and can retry from it', () => {
    const failed = nextCalibrationStep({ kind: 'checking' }, { type: 'failed', message: 'The unit moved.' });
    expect(failed).toEqual({ kind: 'error', message: 'The unit moved.' });
    expect(nextCalibrationStep(failed, { type: 'start' })).toEqual({ kind: 'checking' });
  });

  it('cancelling a confirmation saves nothing and returns to idle', () => {
    expect(nextCalibrationStep({ kind: 'confirm', preview }, { type: 'cancel' })).toEqual({ kind: 'idle' });
  });

  it('ignores events that do not belong to the current step', () => {
    const confirm: CalibrationStep = { kind: 'confirm', preview };
    expect(nextCalibrationStep(confirm, { type: 'applied', result: preview })).toBe(confirm);
    const applying: CalibrationStep = { kind: 'applying', preview };
    expect(nextCalibrationStep(applying, { type: 'start' })).toBe(applying);
    expect(nextCalibrationStep(applying, { type: 'cancel' })).toBe(applying);
    expect(nextCalibrationStep({ kind: 'idle' }, { type: 'confirm' })).toEqual({ kind: 'idle' });
  });

  it('closing resets to idle', () => {
    expect(nextCalibrationStep({ kind: 'error', message: 'x' }, { type: 'close' })).toEqual({ kind: 'idle' });
  });
});

describe('calibrationSourceLabel', () => {
  it('describes a saved screen calibration with its time', () => {
    expect(calibrationSourceLabel(status())).toBe('Calibrated 2026-11-05 22:40');
  });

  it('says when startup flags control the offsets', () => {
    expect(calibrationSourceLabel(status({ pitch_source: 'command_line', can_calibrate: false }))).toBe(
      'Set by startup flags'
    );
    expect(calibrationSourceLabel(status({ roll_source: 'command_line', can_calibrate: false }))).toBe(
      'Set by startup flags'
    );
  });

  it('says when the sensor was never calibrated', () => {
    expect(
      calibrationSourceLabel(status({ pitch_source: 'default', roll_source: 'default', calibrated_at: null }))
    ).toBe('Not calibrated');
  });

  it('handles a saved calibration without a time', () => {
    expect(calibrationSourceLabel(status({ calibrated_at: null }))).toBe('Calibrated');
  });
});

describe('launchAngleShiftNote', () => {
  it('gives the radar tilt change and which way launch angles move', () => {
    expect(launchAngleShiftNote(-0.213)).toBe('Radar tilt changes by -0.2°, so launch angles will read lower.');
    expect(launchAngleShiftNote(0.46)).toBe('Radar tilt changes by +0.5°, so launch angles will read higher.');
  });

  it('says launch angles are unchanged when the shift rounds to zero', () => {
    expect(launchAngleShiftNote(0.04)).toBe('Radar tilt is unchanged, so launch angles are unchanged.');
    expect(launchAngleShiftNote(-0.04)).toBe('Radar tilt is unchanged, so launch angles are unchanged.');
  });
});

describe('requests', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('posts the apply flag and returns the parsed body', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => preview });
    vi.stubGlobal('fetch', fetchMock);

    await expect(requestLevelCalibration(false)).resolves.toEqual({ ok: true, body: preview });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain('/api/inclinometer/level-calibration');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({ apply: false });
  });

  it('returns the server message when the request is refused', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, json: async () => ({ error: 'moving', message: 'The unit moved.' }) })
    );

    await expect(requestLevelCalibration(true)).resolves.toEqual({ ok: false, message: 'The unit moved.' });
  });

  it('falls back to a generic message when the refusal has no body', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        json: async () => {
          throw new SyntaxError('no json');
        },
      })
    );

    await expect(requestLevelCalibrationUndo()).resolves.toEqual({
      ok: false,
      message: 'The launch monitor refused the request.',
    });
  });

  it('reports a network failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));

    await expect(requestLevelCalibration(false)).resolves.toEqual({
      ok: false,
      message: 'Could not reach the launch monitor.',
    });
  });
});
