/** Camera tab "Calibrate level": dialog steps, labels, and server requests. */
import { formatLevelDegrees, type LevelCalibrationStatus } from './levelReadout';
import { getServerOrigin } from './serverOrigin';

const CALIBRATION_URL = `${getServerOrigin()}/api/inclinometer/level-calibration`;
const UNDO_URL = `${CALIBRATION_URL}/undo`;

interface OffsetPair {
  zero_offset_deg: number;
  roll_zero_offset_deg: number;
}

/** Body of POST /api/inclinometer/level-calibration. */
export interface CalibrationPreview {
  applied: boolean;
  current: OffsetPair;
  proposed: OffsetPair;
  /** Proposed minus current offset; the pitch change shifts the radar tilt by the same amount. */
  change: { pitch_deg: number; roll_deg: number };
  reading: {
    raw_pitch_deg: number;
    raw_roll_deg: number;
    pitch_std_deg: number;
    roll_std_deg: number;
    snapshot_count: number;
  };
  calibrated_at: string;
}

export type CalibrationStep =
  | { kind: 'idle'; notice?: string }
  | { kind: 'checking' }
  | { kind: 'confirm'; preview: CalibrationPreview }
  | { kind: 'applying'; preview: CalibrationPreview }
  | { kind: 'done'; result: CalibrationPreview }
  | { kind: 'undoing' }
  | { kind: 'error'; message: string };

export type CalibrationEvent =
  | { type: 'start' }
  | { type: 'previewed'; preview: CalibrationPreview }
  | { type: 'confirm' }
  | { type: 'applied'; result: CalibrationPreview }
  | { type: 'undo' }
  | { type: 'undone' }
  | { type: 'failed'; message: string }
  | { type: 'cancel' }
  | { type: 'close' };

/** Advance the dialog; events that do not fit the current step are ignored. */
export function nextCalibrationStep(step: CalibrationStep, event: CalibrationEvent): CalibrationStep {
  const busy = step.kind === 'checking' || step.kind === 'applying' || step.kind === 'undoing';
  switch (event.type) {
    case 'start':
      return busy || step.kind === 'confirm' ? step : { kind: 'checking' };
    case 'previewed':
      return step.kind === 'checking' ? { kind: 'confirm', preview: event.preview } : step;
    case 'confirm':
      return step.kind === 'confirm' ? { kind: 'applying', preview: step.preview } : step;
    case 'applied':
      return step.kind === 'applying' ? { kind: 'done', result: event.result } : step;
    case 'undo':
      return step.kind === 'idle' || step.kind === 'done' ? { kind: 'undoing' } : step;
    case 'undone':
      return step.kind === 'undoing' ? { kind: 'idle', notice: 'Previous calibration restored.' } : step;
    case 'failed':
      return busy ? { kind: 'error', message: event.message } : step;
    case 'cancel':
      return step.kind === 'confirm' || step.kind === 'error' ? { kind: 'idle' } : step;
    case 'close':
      return { kind: 'idle' };
  }
}

/** Where the zero offsets in use came from, for the dialog header. */
export function calibrationSourceLabel(status: LevelCalibrationStatus): string {
  if (status.pitch_source === 'command_line' || status.roll_source === 'command_line') {
    return 'Set by startup flags';
  }
  if (status.pitch_source === 'saved' || status.roll_source === 'saved') {
    // Shown as the launch monitor's local time; its clock may be unset at the range.
    const when = status.calibrated_at?.slice(0, 16).replace('T', ' ');
    return when ? `Calibrated ${when}` : 'Calibrated';
  }
  return 'Not calibrated';
}

/** Plain-language effect of the pitch offset change on launch angle. */
export function launchAngleShiftNote(pitchChangeDeg: number): string {
  const shown = formatLevelDegrees(pitchChangeDeg);
  if (shown === '0.0°') return 'Radar tilt is unchanged, so launch angles are unchanged.';
  const direction = pitchChangeDeg > 0 ? 'higher' : 'lower';
  return `Radar tilt changes by ${shown}, so launch angles will read ${direction}.`;
}

export type CalibrationRequestResult<T> = { ok: true; body: T } | { ok: false; message: string };

async function post<T>(url: string, body: object): Promise<CalibrationRequestResult<T>> {
  let response: Response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      cache: 'no-store',
    });
  } catch {
    return { ok: false, message: 'Could not reach the launch monitor.' };
  }
  let payload: { message?: unknown } | null = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const message = typeof payload?.message === 'string' ? payload.message : 'The launch monitor refused the request.';
    return { ok: false, message };
  }
  return { ok: true, body: payload as T };
}

/** Preview (apply=false) or save and apply (apply=true) a level-floor calibration. */
export function requestLevelCalibration(apply: boolean): Promise<CalibrationRequestResult<CalibrationPreview>> {
  return post<CalibrationPreview>(CALIBRATION_URL, { apply });
}

/** Restore the offsets the last calibration replaced. */
export function requestLevelCalibrationUndo(): Promise<CalibrationRequestResult<unknown>> {
  return post<unknown>(UNDO_URL, {});
}
