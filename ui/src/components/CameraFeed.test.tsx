import { renderToString } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import type { CameraCaptureSettings } from '../stores/useCameraStore';
import { verticalViewTargets } from '../utils/cameraView';
import { CameraFeed, CaptureSettingsPanel } from './CameraFeed';

const captureSettings: CameraCaptureSettings = {
  available: true,
  enabled: true,
  running: true,
  armed: true,
  width: 320,
  height: 200,
  fps: 600,
  pre_ms: 150,
  post_ms: 50,
  pre_frames: 90,
  post_frames: 30,
  exposure_us: 500,
  max_exposure_us: 1666,
  gain: 2,
  rotate_180: true,
  alignment_x_pct: 48,
  alignment_y_pct: 55,
  raw_crop_adjustable: true,
  vertical_offset_px: -20,
  vertical_offset_min_px: -70,
  vertical_offset_max_px: 70,
  vertical_offset_step_px: 10,
  auto_exposure: {
    enabled: true,
    status: 'ready',
    analysis_eligible: true,
    message: 'Impact-area exposure and contrast look good',
    motion_blur_risk: 'low',
    exposure_us: 500,
    gain: 12,
    observation: {
      sample_available: true,
      status: 'good',
      median: 108,
      contrast: 94,
    },
  },
};

describe('CameraFeed', () => {
  it('maps view direction through the 180-degree mount rotation', () => {
    expect(verticalViewTargets(0, 10, true)).toEqual({ up: 10, down: -10 });
    expect(verticalViewTargets(0, 10, false)).toEqual({ up: -10, down: 10 });
  });

  it('renders the dominant preview workspace and operator settings', () => {
    const html = renderToString(
      <CameraFeed captureSettings={captureSettings} captureSettingsError={null} onUpdateCaptureSettings={vi.fn()} />
    );

    expect(html).toContain('camera-feed__workspace');
    expect(html).toContain('Camera setup');
    expect(html).toContain('Automatic exposure');
    expect(html).toContain('calibrates at startup or on request');
    expect(html).not.toContain('checks every 5 seconds');
    expect(html).toContain('Live view');
    expect(html).toContain('camera-feed__exposure-quality');
    expect(html).toContain('Camera analysis active');
    expect(html).toContain('Impact median');
    expect(html).toContain('Motion blur risk');
    expect(html).toContain('500<!-- --> µs');
    expect(html).not.toContain('Environment profile');
    expect(html).not.toContain('Darker');
    expect(html).not.toContain('Brighter');
    expect(html).toContain('Ball placement guide');
    expect(html).toContain('50% across · 78% down');
    expect(html).not.toContain('type="range"');
    expect(html).not.toContain('Apply alignment guide');
    expect(html).toContain('Sensor view');
    expect(html).toContain('View up');
    expect(html).toContain('View down');
    expect(html).toContain('-20 px');
    expect(html).toContain('320 × 200');
    expect(html).toContain('600 fps');
    expect(html).toContain('Armed');
    expect(html).not.toContain('Recalibrate exposure');
  });

  it('shows the live view, not the startup verdict, after lighting changes', () => {
    // Locked "Lighting needed" indoors, then moved into sunlight.
    const lockedDark = {
      ...captureSettings.auto_exposure!,
      status: 'lighting_required' as const,
      analysis_eligible: false,
      message: 'Camera lighting is insufficient; add or redirect light toward the ball',
      exposure_us: 1250,
      gain: 15.9,
      observation: { sample_available: true, status: 'too_dark' as const, median: 55, contrast: 11 },
    };
    const html = renderToString(
      <CaptureSettingsPanel
        settings={{ ...captureSettings, auto_exposure: lockedDark }}
        exposureQuality={{
          sample_available: true,
          status: 'too_bright',
          message: 'Impact area is clipping; reducing exposure',
          median: 255,
          contrast: 0,
          clipped_pct: 100,
          auto_exposure: lockedDark,
        }}
        error={null}
        onUpdate={vi.fn()}
        onRecalibrate={vi.fn()}
      />
    );

    expect(html).toContain('Lighting needed');
    expect(html).toContain('Too bright');
    expect(html).toContain('Lighting has changed since startup');
    expect(html).toContain('tap Recalibrate exposure');
    expect(html).toContain('>Recalibrate exposure</button>');
    expect(html).not.toContain('add or redirect light toward the ball');
    expect(html).toContain('255');
    expect(html).toContain('100<!-- -->%');
    expect(html).toContain('1250<!-- --> µs');
  });

  it('keeps the startup guidance when the live view agrees with it', () => {
    const lockedDark = {
      ...captureSettings.auto_exposure!,
      status: 'lighting_required' as const,
      analysis_eligible: false,
      message: 'Camera lighting is insufficient; add or redirect light toward the ball',
      observation: { sample_available: true, status: 'too_dark' as const, median: 55, contrast: 11 },
    };
    const html = renderToString(
      <CaptureSettingsPanel
        settings={{ ...captureSettings, auto_exposure: lockedDark }}
        exposureQuality={{
          sample_available: true,
          status: 'too_dark',
          median: 59,
          contrast: 7,
          clipped_pct: 0,
          auto_exposure: lockedDark,
        }}
        error={null}
        onUpdate={vi.fn()}
        onRecalibrate={vi.fn()}
      />
    );

    expect(html).toContain('add or redirect light toward the ball');
    expect(html).not.toContain('Lighting has changed since startup');
    expect(html).toContain('59');
    expect(html).toContain('>Recalibrate exposure</button>');
  });

  it('disables the recalibrate button right after it is tapped', () => {
    const lockedDark = {
      ...captureSettings.auto_exposure!,
      status: 'lighting_required' as const,
      analysis_eligible: false,
      observation: { sample_available: true, status: 'too_dark' as const },
    };
    const html = renderToString(
      <CaptureSettingsPanel
        settings={{ ...captureSettings, auto_exposure: lockedDark }}
        exposureQuality={{ sample_available: true, status: 'too_bright', auto_exposure: lockedDark }}
        error={null}
        onUpdate={vi.fn()}
        onRecalibrate={vi.fn()}
        recalibrationPending
      />
    );

    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Recalibrating…<\/button>/);
  });

  it('explains lighting failure without disabling capture', () => {
    const html = renderToString(
      <CameraFeed
        captureSettings={{
          ...captureSettings,
          auto_exposure: {
            ...captureSettings.auto_exposure!,
            status: 'lighting_required',
            analysis_eligible: false,
            message: 'Camera lighting is insufficient; add or redirect light toward the ball',
          },
        }}
        captureSettingsError={null}
        onUpdateCaptureSettings={vi.fn()}
      />
    );

    expect(html).toContain('Lighting needed');
    expect(html).toContain('Radar fallback active');
    expect(html).toContain('Preview and raw clips continue recording');
    expect(html).toContain('Armed');
  });
});
