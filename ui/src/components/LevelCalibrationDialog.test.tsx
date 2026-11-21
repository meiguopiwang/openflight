import { renderToString } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import type { CalibrationPreview, CalibrationStep } from '../utils/levelCalibration';
import type { LevelCalibrationStatus, LevelView } from '../utils/levelReadout';
import { LevelCalibrationDialog } from './LevelCalibrationDialog';

const reading: LevelView = {
  kind: 'reading',
  pitchDeg: 0.21,
  rollDeg: 0.3,
  radarTiltDeg: 9.61,
  settling: false,
  message: null,
};

const calibration: LevelCalibrationStatus = {
  pitch_source: 'saved',
  roll_source: 'saved',
  calibrated_at: '2026-11-05T22:30:00',
  can_calibrate: true,
  can_undo: false,
};

const preview: CalibrationPreview = {
  applied: false,
  current: { zero_offset_deg: 1.663, roll_zero_offset_deg: -3.05 },
  proposed: { zero_offset_deg: 1.45, roll_zero_offset_deg: -3.35 },
  change: { pitch_deg: -0.213, roll_deg: -0.3 },
  reading: { raw_pitch_deg: -1.45, raw_roll_deg: 3.35, pitch_std_deg: 0.05, roll_std_deg: 0.06, snapshot_count: 30 },
  calibrated_at: '2026-11-05T22:40:00',
};

function render(step: CalibrationStep, overrides: Partial<LevelCalibrationStatus> = {}, view: LevelView = reading) {
  return renderToString(
    <LevelCalibrationDialog
      view={view}
      calibration={{ ...calibration, ...overrides }}
      step={step}
      onStart={vi.fn()}
      onConfirm={vi.fn()}
      onUndo={vi.fn()}
      onCancel={vi.fn()}
      onClose={vi.fn()}
    />
  );
}

describe('LevelCalibrationDialog', () => {
  it('shows the live angles, where the calibration came from, and how to calibrate', () => {
    const html = render({ kind: 'idle' });

    expect(html).toContain('role="dialog"');
    expect(html).toContain('aria-modal="true"');
    expect(html).toContain('+0.2°');
    expect(html).toContain('+0.3°');
    expect(html).toContain('Radar tilt 9.6°');
    expect(html).toContain('Calibrated 2026-11-05 22:30');
    expect(html).toContain('level floor');
    expect(html).toMatch(/panel-action--primary[^>]*>Calibrate level</);
    expect(html).not.toContain('Undo last calibration');
  });

  it('offers undo only when the server says it can', () => {
    expect(render({ kind: 'idle' }, { can_undo: true })).toContain('Undo last calibration');
  });

  it('disables calibration and explains why when startup flags set the offsets', () => {
    const html = render({ kind: 'idle' }, { pitch_source: 'command_line', can_calibrate: false });

    expect(html).toContain('Set by startup flags');
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Calibrate level</);
    expect(html).toContain('--inclinometer-zero-offset');
  });

  it('shows a notice after an undo', () => {
    expect(render({ kind: 'idle', notice: 'Previous calibration restored.' })).toContain(
      'Previous calibration restored.'
    );
  });

  it('shows progress while checking the unit is still', () => {
    const html = render({ kind: 'checking' });

    expect(html).toContain('Checking the unit is still');
    expect(html).not.toContain('>Calibrate level<');
  });

  it('confirms with before and after readings and the launch angle effect', () => {
    const html = render({ kind: 'confirm', preview });

    // Tilt now reads raw + current offset = -1.45 + 1.663 = +0.2°; after calibration 0.0°.
    expect(html).toMatch(/Tilt[\s\S]*\+0\.2°[\s\S]*→[\s\S]*0\.0°/);
    expect(html).toMatch(/Lean[\s\S]*\+0\.3°[\s\S]*→[\s\S]*0\.0°/);
    expect(html).toContain('Radar tilt changes by -0.2°, so launch angles will read lower.');
    expect(html).toMatch(/panel-action--primary[^>]*>Calibrate</);
    expect(html).toMatch(/panel-action--secondary[^>]*>Cancel</);
  });

  it('shows the saved result with an undo button', () => {
    const html = render({ kind: 'done', result: { ...preview, applied: true } });

    expect(html).toContain('Calibrated. Tilt and Lean now read 0.0°.');
    expect(html).toContain('launch angles will read lower');
    expect(html).toMatch(/>Undo</);
    expect(html).toMatch(/>Done</);
  });

  it('shows the server message on failure with a retry', () => {
    const html = render({ kind: 'error', message: 'The unit moved. Keep it still for 3 seconds, then try again.' });

    expect(html).toContain('The unit moved.');
    expect(html).toMatch(/>Try again</);
  });

  it('shows saving and restoring progress without action buttons', () => {
    expect(render({ kind: 'applying', preview })).toContain('Saving');
    expect(render({ kind: 'undoing' })).toContain('Restoring');
    expect(render({ kind: 'undoing' })).not.toContain('>Undo<');
  });

  it('asks to hold still when there is no live reading yet', () => {
    expect(render({ kind: 'idle' }, {}, { kind: 'waiting', message: 'Hold still…' })).toContain('Hold still…');
  });
});
