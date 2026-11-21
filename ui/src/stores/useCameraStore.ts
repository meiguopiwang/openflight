import { create } from 'zustand';

export interface CameraCaptureSettings {
  available: boolean;
  enabled?: boolean;
  running?: boolean;
  armed?: boolean;
  width?: number;
  height?: number;
  fps?: number;
  pre_ms?: number;
  post_ms?: number;
  pre_frames?: number;
  post_frames?: number;
  buffered_frames?: number;
  required_pre_frames?: number;
  exposure_us?: number;
  max_exposure_us?: number;
  gain?: number;
  stream?: string;
  rotate_180?: boolean;
  mirror_horizontal?: boolean;
  roll_correction_deg?: number;
  alignment_x_pct?: number;
  alignment_y_pct?: number;
  raw_crop_adjustable?: boolean;
  vertical_offset_px?: number;
  vertical_offset_min_px?: number;
  vertical_offset_max_px?: number;
  vertical_offset_step_px?: number;
  auto_exposure?: CameraAutoExposureStatus;
}

export type CameraExposureObservationStatus = 'good' | 'too_dark' | 'too_bright' | 'marginal' | 'unavailable';

/** Impact-area brightness rating from one frame (server `measure_exposure`). */
export interface CameraExposureObservation {
  sample_available: boolean;
  status: CameraExposureObservationStatus;
  recommendation?: 'brighter' | 'darker' | 'hold';
  message?: string;
  median?: number | null;
  p90?: number | null;
  contrast?: number | null;
  clipped_pct?: number | null;
  dark_pct?: number | null;
}

export interface CameraAutoExposureStatus {
  enabled: boolean;
  status: 'ready' | 'adjusting' | 'lighting_required' | 'unavailable';
  analysis_eligible: boolean;
  message: string;
  motion_blur_risk: 'low' | 'elevated' | 'high';
  capture_deferred?: boolean;
  exposure_us?: number;
  gain?: number;
  /** The observation that produced the startup (locked) decision. */
  observation?: CameraExposureObservation;
}

/** `/api/camera/exposure-quality`: the latest frame plus the locked startup state. */
export interface CameraExposureQuality extends CameraExposureObservation {
  auto_exposure?: CameraAutoExposureStatus;
}

interface CameraState {
  captureSettings: CameraCaptureSettings;
  captureSettingsError: string | null;
  setCaptureSettings: (settings: CameraCaptureSettings) => void;
  setCaptureSettingsError: (error: string | null) => void;
}

export const useCameraStore = create<CameraState>((set) => ({
  captureSettings: { available: false },
  captureSettingsError: null,
  setCaptureSettings: (settings) => set({ captureSettings: settings, captureSettingsError: null }),
  setCaptureSettingsError: (error) => set({ captureSettingsError: error }),
}));
