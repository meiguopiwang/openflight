import { useEffect, useReducer, useState } from 'react';
import { LevelCalibrationDialog } from './LevelCalibrationDialog';
import {
  nextCalibrationStep,
  requestLevelCalibration,
  requestLevelCalibrationUndo,
  type CalibrationEvent,
} from '../utils/levelCalibration';
import {
  formatLevelDegrees,
  isLeanLevel,
  nextLevelView,
  type LevelCalibrationStatus,
  type LevelFetchResult,
  type LevelView,
} from '../utils/levelReadout';
import { getServerOrigin } from '../utils/serverOrigin';
import './LevelReadout.css';

const LEVEL_URL = `${getServerOrigin()}/api/inclinometer/level`;
const LEVEL_REFRESH_MS = 500;

interface LevelReadoutProps {
  /** Starting state; tests render fixed states, the app starts by checking. */
  initialView?: LevelView;
  initialOpen?: boolean;
}

async function fetchLevel(): Promise<LevelFetchResult> {
  try {
    const response = await fetch(`${LEVEL_URL}?t=${Date.now()}`, { cache: 'no-store' });
    if (response.status === 404) return { kind: 'unavailable' };
    if (!response.ok) return { kind: 'failed' };
    return { kind: 'response', body: await response.json() };
  } catch {
    return { kind: 'failed' };
  }
}

function PillContents({ view }: { view: LevelView }) {
  if (view.kind !== 'reading') {
    return (
      <>
        <span className="level-readout__label">Level</span>
        <span className="level-readout__message">{view.kind === 'waiting' ? view.message : 'checking'}</span>
      </>
    );
  }
  const leanLevel = isLeanLevel(view.rollDeg);
  return (
    <>
      <span className="level-readout__label">Level</span>
      <span className="level-readout__value">
        Tilt <strong>{formatLevelDegrees(view.pitchDeg)}</strong>
      </span>
      <span className={`level-readout__value level-readout__lean--${leanLevel ? 'ok' : 'warn'}`}>
        Lean <strong>{formatLevelDegrees(view.rollDeg)}</strong>
      </span>
      {view.message && <span className="level-readout__message">{view.message}</span>}
    </>
  );
}

/**
 * Live enclosure tilt for setup: forward/back relative to the calibrated zero
 * and sideways lean. Tap to open the level dialog and calibrate on a level
 * floor. Hidden when the server has no inclinometer.
 */
export function LevelReadout({ initialView = { kind: 'checking' }, initialOpen = false }: LevelReadoutProps) {
  const [view, setView] = useState<LevelView>(initialView);
  const [calibration, setCalibration] = useState<LevelCalibrationStatus | null>(null);
  const [open, setOpen] = useState(initialOpen);
  const [step, dispatch] = useReducer(nextCalibrationStep, { kind: 'idle' });

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    // Chain timeouts rather than an interval so a slow response never overlaps the next poll.
    const poll = async () => {
      const result = await fetchLevel();
      if (cancelled) return;
      setView((previous) => nextLevelView(previous, result));
      if (result.kind === 'response') setCalibration(result.body.calibration ?? null);
      if (result.kind !== 'unavailable') timer = setTimeout(poll, LEVEL_REFRESH_MS);
    };

    poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, []);

  // Each busy step owns exactly one request; the reducer ignores late replies.
  useEffect(() => {
    let cancelled = false;
    const finish = (event: CalibrationEvent) => {
      if (!cancelled) dispatch(event);
    };
    if (step.kind === 'checking') {
      requestLevelCalibration(false).then((result) =>
        finish(result.ok ? { type: 'previewed', preview: result.body } : { type: 'failed', message: result.message })
      );
    } else if (step.kind === 'applying') {
      requestLevelCalibration(true).then((result) =>
        finish(result.ok ? { type: 'applied', result: result.body } : { type: 'failed', message: result.message })
      );
    } else if (step.kind === 'undoing') {
      requestLevelCalibrationUndo().then((result) =>
        finish(result.ok ? { type: 'undone' } : { type: 'failed', message: result.message })
      );
    }
    return () => {
      cancelled = true;
    };
  }, [step.kind]);

  if (view.kind === 'hidden') return null;

  const settling = view.kind === 'reading' && view.settling;
  const close = () => {
    dispatch({ type: 'close' });
    setOpen(false);
  };
  return (
    <>
      <button
        type="button"
        className={`level-readout${view.kind === 'reading' ? '' : ' level-readout--waiting'}${
          settling ? ' level-readout--settling' : ''
        }`}
        aria-label="Level, tap to calibrate"
        onClick={() => setOpen(true)}
      >
        <PillContents view={view} />
      </button>
      {open && (
        <LevelCalibrationDialog
          view={view}
          calibration={calibration}
          step={step}
          onStart={() => dispatch({ type: 'start' })}
          onConfirm={() => dispatch({ type: 'confirm' })}
          onUndo={() => dispatch({ type: 'undo' })}
          onCancel={() => dispatch({ type: 'cancel' })}
          onClose={close}
        />
      )}
    </>
  );
}
