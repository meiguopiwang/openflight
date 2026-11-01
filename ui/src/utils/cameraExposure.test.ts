import { describe, expect, it } from 'vitest';
import type { CameraAutoExposureStatus } from '../stores/useCameraStore';
import { LIVE_EXPOSURE_LABELS, lightingChangeMessage, lightingChangedSinceStartup } from './cameraExposure';

function startup(
  status: CameraAutoExposureStatus['status'],
  observationStatus: NonNullable<CameraAutoExposureStatus['observation']>['status']
): CameraAutoExposureStatus {
  return {
    enabled: true,
    status,
    analysis_eligible: status === 'ready',
    message: 'startup message',
    motion_blur_risk: 'low',
    observation: { sample_available: true, status: observationStatus },
  };
}

describe('lightingChangedSinceStartup', () => {
  it('flags a sunlit view after an indoor startup that locked too dark', () => {
    // 2026-11-01: locked "Lighting needed" indoors, then moved into sun.
    expect(lightingChangedSinceStartup(startup('lighting_required', 'too_dark'), 'too_bright')).toBe(true);
  });

  it('flags a usable view after a startup that needed more light', () => {
    expect(lightingChangedSinceStartup(startup('lighting_required', 'too_dark'), 'good')).toBe(true);
    expect(lightingChangedSinceStartup(startup('lighting_required', 'too_bright'), 'marginal')).toBe(true);
  });

  it('flags a ready startup whose live view is now clipping or dark', () => {
    expect(lightingChangedSinceStartup(startup('ready', 'good'), 'too_bright')).toBe(true);
    expect(lightingChangedSinceStartup(startup('ready', 'good'), 'too_dark')).toBe(true);
  });

  it('does not flag unchanged or still-usable lighting', () => {
    expect(lightingChangedSinceStartup(startup('ready', 'good'), 'good')).toBe(false);
    expect(lightingChangedSinceStartup(startup('ready', 'good'), 'marginal')).toBe(false);
    expect(lightingChangedSinceStartup(startup('ready', 'marginal'), 'good')).toBe(false);
    expect(lightingChangedSinceStartup(startup('lighting_required', 'too_dark'), 'too_dark')).toBe(false);
    expect(lightingChangedSinceStartup(startup('lighting_required', 'too_bright'), 'too_bright')).toBe(false);
  });

  it('does not flag while calibrating or before a live sample exists', () => {
    expect(lightingChangedSinceStartup(startup('adjusting', 'too_dark'), 'too_bright')).toBe(false);
    expect(lightingChangedSinceStartup(startup('unavailable', 'unavailable'), 'too_bright')).toBe(false);
    expect(lightingChangedSinceStartup(startup('ready', 'good'), 'unavailable')).toBe(false);
    expect(lightingChangedSinceStartup(startup('ready', 'good'), undefined)).toBe(false);
    expect(lightingChangedSinceStartup(undefined, 'too_bright')).toBe(false);
  });
});

describe('lightingChangeMessage', () => {
  it('tells the operator what changed and how to recalibrate', () => {
    expect(lightingChangeMessage('too_bright')).toMatch(/too bright.*restart OpenFlight to recalibrate/i);
    expect(lightingChangeMessage('too_dark')).toMatch(/too dark.*restart OpenFlight to recalibrate/i);
    expect(lightingChangeMessage('good')).toMatch(/usable.*restart OpenFlight to recalibrate/i);
    expect(lightingChangeMessage('marginal')).toMatch(/usable.*restart OpenFlight to recalibrate/i);
  });
});

describe('LIVE_EXPOSURE_LABELS', () => {
  it('names every live status in plain words', () => {
    expect(LIVE_EXPOSURE_LABELS).toEqual({
      good: 'Good',
      marginal: 'Usable',
      too_dark: 'Too dark',
      too_bright: 'Too bright',
      unavailable: 'Checking',
    });
  });
});
