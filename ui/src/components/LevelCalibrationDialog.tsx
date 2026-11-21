import { PanelAction } from './panel/PanelAction';
import {
  calibrationSourceLabel,
  launchAngleShiftNote,
  type CalibrationPreview,
  type CalibrationStep,
} from '../utils/levelCalibration';
import { formatLevelDegrees, type LevelCalibrationStatus, type LevelView } from '../utils/levelReadout';
import './LevelCalibrationDialog.css';

interface LevelCalibrationDialogProps {
  view: LevelView;
  calibration: LevelCalibrationStatus | null;
  step: CalibrationStep;
  onStart: () => void;
  onConfirm: () => void;
  onUndo: () => void;
  onCancel: () => void;
  onClose: () => void;
}

function LiveAngles({ view }: { view: LevelView }) {
  if (view.kind !== 'reading') {
    return <p className="level-dialog__hint">{view.kind === 'waiting' ? view.message : 'Reading the tilt sensor…'}</p>;
  }
  return (
    <div className={`level-dialog__angles${view.settling ? ' level-dialog__angles--settling' : ''}`}>
      <div>
        <span className="level-dialog__angle-label">Tilt</span>
        <strong>{formatLevelDegrees(view.pitchDeg)}</strong>
      </div>
      <div>
        <span className="level-dialog__angle-label">Lean</span>
        <strong>{formatLevelDegrees(view.rollDeg)}</strong>
      </div>
      {view.radarTiltDeg !== null && (
        <p className="level-dialog__hint">{`Radar tilt ${formatLevelDegrees(view.radarTiltDeg, { signed: false })}`}</p>
      )}
      {view.message && <p className="level-dialog__hint">{view.message}</p>}
    </div>
  );
}

/** Readings before and after, from the same still window the offsets came from. */
function BeforeAfter({ preview }: { preview: CalibrationPreview }) {
  const tiltNow = preview.reading.raw_pitch_deg + preview.current.zero_offset_deg;
  const leanNow = preview.reading.raw_roll_deg + preview.current.roll_zero_offset_deg;
  return (
    <dl className="level-dialog__change">
      <dt>Tilt</dt>
      <dd>
        {formatLevelDegrees(tiltNow)} → {formatLevelDegrees(0)}
      </dd>
      <dt>Lean</dt>
      <dd>
        {formatLevelDegrees(leanNow)} → {formatLevelDegrees(0)}
      </dd>
    </dl>
  );
}

function StepBody({
  step,
  calibration,
  onStart,
  onConfirm,
  onUndo,
  onCancel,
  onClose,
}: Omit<LevelCalibrationDialogProps, 'view'>) {
  switch (step.kind) {
    case 'idle': {
      const canCalibrate = calibration?.can_calibrate ?? false;
      return (
        <>
          {step.notice && <p className="level-dialog__notice">{step.notice}</p>}
          <p className="level-dialog__detail">
            Put the unit on a level floor (check it with a level), keep it still for 3 seconds, then calibrate. Tilt and
            Lean will read 0.0° in that position.
          </p>
          {!canCalibrate && (
            <p className="level-dialog__detail level-dialog__detail--warn">
              The offsets are set by --inclinometer-zero-offset or --inclinometer-roll-zero-offset in the launch
              command. Remove them to calibrate here.
            </p>
          )}
          <div className="level-dialog__actions">
            <PanelAction variant="primary" disabled={!canCalibrate} onClick={onStart}>
              Calibrate level
            </PanelAction>
            {calibration?.can_undo && (
              <PanelAction variant="secondary" onClick={onUndo}>
                Undo last calibration
              </PanelAction>
            )}
            <PanelAction variant="secondary" onClick={onClose}>
              Close
            </PanelAction>
          </div>
        </>
      );
    }
    case 'checking':
      return <p className="level-dialog__detail">Checking the unit is still…</p>;
    case 'confirm':
      return (
        <>
          <BeforeAfter preview={step.preview} />
          <p className="level-dialog__detail">{launchAngleShiftNote(step.preview.change.pitch_deg)}</p>
          <div className="level-dialog__actions">
            <PanelAction variant="primary" autoFocus onClick={onConfirm}>
              Calibrate
            </PanelAction>
            <PanelAction variant="secondary" onClick={onCancel}>
              Cancel
            </PanelAction>
          </div>
        </>
      );
    case 'applying':
      return <p className="level-dialog__detail">Saving calibration…</p>;
    case 'done':
      return (
        <>
          <p className="level-dialog__notice">Calibrated. Tilt and Lean now read 0.0°.</p>
          <p className="level-dialog__detail">{launchAngleShiftNote(step.result.change.pitch_deg)}</p>
          <div className="level-dialog__actions">
            <PanelAction variant="secondary" onClick={onUndo}>
              Undo
            </PanelAction>
            <PanelAction variant="primary" onClick={onClose}>
              Done
            </PanelAction>
          </div>
        </>
      );
    case 'undoing':
      return <p className="level-dialog__detail">Restoring the previous calibration…</p>;
    case 'error':
      return (
        <>
          <p className="level-dialog__detail level-dialog__detail--warn">{step.message}</p>
          <div className="level-dialog__actions">
            <PanelAction variant="primary" onClick={onStart}>
              Try again
            </PanelAction>
            <PanelAction variant="secondary" onClick={onCancel}>
              Close
            </PanelAction>
          </div>
        </>
      );
  }
}

/** Live level angles and the on-screen level-floor calibration. */
export function LevelCalibrationDialog({ view, calibration, step, ...actions }: LevelCalibrationDialogProps) {
  const busy = step.kind === 'checking' || step.kind === 'applying' || step.kind === 'undoing';
  return (
    <div className="level-dialog">
      <button
        type="button"
        className="level-dialog__scrim"
        aria-label="Close level"
        disabled={busy}
        onClick={actions.onClose}
      />
      <div className="level-dialog__box" role="dialog" aria-modal="true" aria-labelledby="level-dialog-title">
        <div className="level-dialog__header">
          <span id="level-dialog-title" className="level-dialog__title">
            Level
          </span>
          {calibration && <span className="level-dialog__source">{calibrationSourceLabel(calibration)}</span>}
        </div>
        <LiveAngles view={view} />
        <StepBody step={step} calibration={calibration} {...actions} />
      </div>
    </div>
  );
}
