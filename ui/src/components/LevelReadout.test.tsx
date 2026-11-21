import { renderToString } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { LevelView } from '../utils/levelReadout';
import { LevelReadout } from './LevelReadout';

const reading: LevelView = {
  kind: 'reading',
  pitchDeg: -0.03,
  rollDeg: 4.07,
  radarTiltDeg: 9.37,
  settling: false,
  message: null,
};

describe('LevelReadout', () => {
  it('shows forward/back tilt and sideways lean', () => {
    const html = renderToString(<LevelReadout initialView={reading} />);

    expect(html).toContain('Level');
    expect(html).toContain('Tilt <strong>0.0°</strong>');
    expect(html).toContain('Lean <strong>+4.1°</strong>');
    expect(html).not.toContain('level-readout--settling');
  });

  it('warns when the lean is beyond the tolerance and not when it is level', () => {
    expect(renderToString(<LevelReadout initialView={reading} />)).toContain('level-readout__lean--warn');
    expect(renderToString(<LevelReadout initialView={{ ...reading, rollDeg: -0.6 }} />)).toContain(
      'level-readout__lean--ok'
    );
  });

  it('dims the last angles and asks to hold still while settling', () => {
    const html = renderToString(<LevelReadout initialView={{ ...reading, settling: true, message: 'Hold still…' }} />);

    expect(html).toContain('level-readout--settling');
    expect(html).toContain('Hold still…');
    expect(html).toContain('+4.1°');
  });

  it('shows checking, waiting, and error messages without angles', () => {
    expect(renderToString(<LevelReadout />)).toContain('checking');
    const waiting = renderToString(<LevelReadout initialView={{ kind: 'waiting', message: 'Tilt sensor error' }} />);
    expect(waiting).toContain('Tilt sensor error');
    expect(waiting).not.toContain('°');
  });

  it('is a button that opens the level dialog', () => {
    const html = renderToString(<LevelReadout initialView={reading} />);

    expect(html).toMatch(/^<button[^>]*type="button"/);
    expect(html).toContain('aria-label="Level, tap to calibrate"');
    expect(html).not.toContain('role="dialog"');
  });

  it('can render with the dialog open', () => {
    const html = renderToString(<LevelReadout initialView={reading} initialOpen />);

    expect(html).toContain('role="dialog"');
    expect(html).toContain('Calibrate level');
  });

  it('renders nothing when the server has no inclinometer', () => {
    expect(renderToString(<LevelReadout initialView={{ kind: 'hidden' }} />)).toBe('');
  });
});
