import { expect, test, type Page } from '@playwright/test';
import { gotoApp, KIOSK_VIEWPORTS } from './helpers';

// The mock backend has no inclinometer, so the level endpoints are stubbed.
const LEVEL = {
  enabled: true,
  status: 'stable',
  age_s: 0.05,
  pitch_deg: 0.22,
  roll_deg: 0.08,
  configured_iwr_tilt_deg: 9.4,
  radar_tilt_deg: 9.62,
  error: null,
  calibration: {
    pitch_source: 'saved',
    roll_source: 'saved',
    calibrated_at: '2026-11-05T22:54:56',
    can_calibrate: true,
    can_undo: true,
  },
};

const PREVIEW = {
  applied: false,
  current: { zero_offset_deg: 1.663, roll_zero_offset_deg: -3.05 },
  proposed: { zero_offset_deg: 1.386, roll_zero_offset_deg: -3.14 },
  change: { pitch_deg: -0.277, roll_deg: -0.09 },
  reading: { raw_pitch_deg: -1.386, raw_roll_deg: 3.14, pitch_std_deg: 0.04, roll_std_deg: 0.04, snapshot_count: 30 },
  calibrated_at: '2026-11-05T22:55:15',
};

async function openLevelDialog(page: Page) {
  await page.route('**/api/inclinometer/level?*', (route) => route.fulfill({ json: LEVEL }));
  await page.route('**/api/inclinometer/level-calibration', (route) => route.fulfill({ json: PREVIEW }));
  await gotoApp(page);
  await page.getByRole('button', { name: 'Close Select club' }).click();
  await page.getByRole('button', { name: 'Camera' }).click();
  await page.getByRole('button', { name: 'Level, tap to calibrate' }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
}

/** Buttons whose label is clipped or that stick out of the dialog box. */
async function misfitButtons(page: Page) {
  return page.locator('.level-dialog__box').evaluate((box) => {
    const bounds = box.getBoundingClientRect();
    return Array.from(box.querySelectorAll('button'))
      .map((button) => {
        const rect = button.getBoundingClientRect();
        return {
          label: button.textContent?.trim() ?? '',
          clipped: button.scrollWidth > button.clientWidth + 1,
          outside: rect.left < bounds.left - 0.5 || rect.right > bounds.right + 0.5,
        };
      })
      .filter((item) => item.clipped || item.outside);
  });
}

for (const viewport of KIOSK_VIEWPORTS) {
  test.describe(`level dialog at ${viewport.width}×${viewport.height}`, () => {
    test.use({ hasTouch: true, viewport });

    test('fits every button, including Undo last calibration', async ({ page }) => {
      await openLevelDialog(page);
      await expect(page.getByRole('button', { name: 'Undo last calibration' })).toBeVisible();

      expect(await misfitButtons(page)).toEqual([]);
    });

    test('fits the confirm step', async ({ page }) => {
      await openLevelDialog(page);
      await page.getByRole('button', { name: 'Calibrate level' }).click();
      await expect(page.getByText('launch angles will read lower')).toBeVisible();

      expect(await misfitButtons(page)).toEqual([]);
    });

    test('keeps the dialog on screen', async ({ page }) => {
      await openLevelDialog(page);
      const box = await page.locator('.level-dialog__box').boundingBox();

      expect(box).not.toBeNull();
      expect(box!.y).toBeGreaterThanOrEqual(0);
      expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height);
      expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width);
    });
  });
}
