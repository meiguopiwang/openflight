import type { CameraAutoExposureStatus, CameraExposureObservationStatus } from '../stores/useCameraStore';

export const LIVE_EXPOSURE_LABELS: Record<CameraExposureObservationStatus, string> = {
  good: 'Good',
  marginal: 'Usable',
  too_dark: 'Too dark',
  too_bright: 'Too bright',
  unavailable: 'Checking',
};

const UNUSABLE: ReadonlySet<CameraExposureObservationStatus> = new Set(['too_dark', 'too_bright']);

/**
 * Whether the live view disagrees with the exposure locked at startup.
 *
 * Exposure is calibrated once and then locked, so the startup verdict goes
 * stale when the unit is moved (e.g. booted indoors, then carried into sun).
 */
export function lightingChangedSinceStartup(
  startup: CameraAutoExposureStatus | undefined,
  liveStatus: CameraExposureObservationStatus | undefined
): boolean {
  if (!startup || !liveStatus || liveStatus === 'unavailable') return false;
  if (startup.status === 'ready') return UNUSABLE.has(liveStatus);
  if (startup.status === 'lighting_required') return liveStatus !== startup.observation?.status;
  return false;
}

export function lightingChangeMessage(liveStatus: CameraExposureObservationStatus): string {
  const now =
    liveStatus === 'too_bright'
      ? 'The view is too bright now'
      : liveStatus === 'too_dark'
        ? 'The view is too dark now'
        : 'Lighting looks usable now';
  return `${now}; tap Recalibrate exposure.`;
}

/** Offer recalibration when the locked verdict is stale or asked for more light. */
export function shouldOfferRecalibration(
  startup: CameraAutoExposureStatus | undefined,
  liveStatus: CameraExposureObservationStatus | undefined
): boolean {
  if (!startup?.enabled) return false;
  return startup.status === 'lighting_required' || lightingChangedSinceStartup(startup, liveStatus);
}
