/**
 * Optimized camera frame capture for mobile perception and OCR.
 *
 * Reuses a single shared canvas element to avoid memory leaks and GC pauses
 * on Android. Implements mode-aware downscaling and JPEG compression to keep
 * payload sizes small (~30KB for vision, ~65KB for OCR) over mobile networks.
 */

let sharedCanvas: HTMLCanvasElement | null = null;
let diffCanvas: HTMLCanvasElement | null = null;
let lastLumaSignature: Uint8Array | null = null;

function getSharedCanvas(): HTMLCanvasElement | null {
  if (typeof document === "undefined") return null;
  if (!sharedCanvas) {
    sharedCanvas = document.createElement("canvas");
  }
  return sharedCanvas;
}

export type VisionFrameMode = "perception" | "ocr" | "thumbnail";

const MODE_PRESETS: Record<VisionFrameMode, { maxDim: number; quality: number }> = {
  // 512px @ 0.60 JPEG yields ~18-25KB payloads for fast AI scene analysis & YOLO inference
  perception: { maxDim: 512, quality: 0.60 },
  // 720px @ 0.68 JPEG yields ~35-45KB payloads with high text readability
  ocr: { maxDim: 720, quality: 0.68 },
  // Quick preview / status checks
  thumbnail: { maxDim: 256, quality: 0.50 },
};

/**
 * Fast sub-millisecond frame change detector (16x16 luma mean difference).
 * Returns true if the camera view has moved or changed beyond the threshold.
 */
export function hasFrameSignificantlyChanged(
  video: HTMLVideoElement | null,
  threshold = 0.08,
): boolean {
  if (!video || typeof video.videoWidth !== "number" || video.videoWidth < 2 || video.videoHeight < 2) {
    return true;
  }
  if (typeof document === "undefined") return true;
  if (!diffCanvas) {
    diffCanvas = document.createElement("canvas");
    diffCanvas.width = 16;
    diffCanvas.height = 16;
  }
  const ctx = diffCanvas.getContext("2d", { willReadFrequently: true, alpha: false });
  if (!ctx) return true;

  try {
    ctx.drawImage(video, 0, 0, 16, 16);
    const imgData = ctx.getImageData(0, 0, 16, 16).data;
    const currentLuma = new Uint8Array(256);
    for (let i = 0; i < 256; i++) {
      const idx = i * 4;
      currentLuma[i] = Math.round(0.299 * imgData[idx] + 0.587 * imgData[idx + 1] + 0.114 * imgData[idx + 2]);
    }

    if (!lastLumaSignature) {
      lastLumaSignature = currentLuma;
      return true;
    }

    let diffSum = 0;
    for (let i = 0; i < 256; i++) {
      diffSum += Math.abs(currentLuma[i] - lastLumaSignature[i]);
    }
    const avgDiff = diffSum / (256 * 255);

    if (avgDiff >= threshold) {
      lastLumaSignature = currentLuma;
      return true;
    }
    return false;
  } catch {
    return true;
  }
}

/**
 * Capture an optimized, compressed JPEG frame from a video element using a
 * reusable canvas to eliminate DOM allocations and garbage collection spikes.
 */
export function captureOptimizedFrame(
  video: HTMLVideoElement | null,
  mode: VisionFrameMode = "perception",
): string | null {
  if (!video || typeof video.videoWidth !== "number" || video.videoWidth < 2 || video.videoHeight < 2) {
    return null;
  }

  const canvas = getSharedCanvas();
  if (!canvas) return null;

  const preset = MODE_PRESETS[mode] ?? MODE_PRESETS.perception;
  const maxDimension = preset.maxDim;
  const quality = preset.quality;

  const scale = Math.min(1, maxDimension / Math.max(video.videoWidth, video.videoHeight));
  const width = Math.max(2, Math.round(video.videoWidth * scale));
  const height = Math.max(2, Math.round(video.videoHeight * scale));

  if (canvas.width !== width) canvas.width = width;
  if (canvas.height !== height) canvas.height = height;

  const context = canvas.getContext("2d", { willReadFrequently: false, alpha: false });
  if (!context) return null;

  try {
    context.drawImage(video, 0, 0, width, height);
    return canvas.toDataURL("image/jpeg", quality);
  } catch {
    return null;
  }
}

/** Legacy-compatible capture helper. */
export function captureFrame(video: HTMLVideoElement | null, maxDimension = 640, quality = 0.68): string | null {
  if (!video || typeof video.videoWidth !== "number" || video.videoWidth < 2 || video.videoHeight < 2) {
    return null;
  }

  const canvas = getSharedCanvas();
  if (!canvas) return null;

  const scale = Math.min(1, maxDimension / Math.max(video.videoWidth, video.videoHeight));
  const width = Math.max(2, Math.round(video.videoWidth * scale));
  const height = Math.max(2, Math.round(video.videoHeight * scale));

  if (canvas.width !== width) canvas.width = width;
  if (canvas.height !== height) canvas.height = height;

  const context = canvas.getContext("2d", { willReadFrequently: false, alpha: false });
  if (!context) return null;

  try {
    context.drawImage(video, 0, 0, width, height);
    return canvas.toDataURL("image/jpeg", quality);
  } catch {
    return null;
  }
}

export function createVideoFrameProvider(
  videoProvider: () => HTMLVideoElement | null,
  maxDimension = 640,
): () => Promise<string | null> {
  return () => Promise.resolve(captureFrame(videoProvider(), maxDimension));
}

export interface ScannerOptions {
  capture: () => string | null;
  detect: (frame: string) => Promise<{ summary: string; priority: string }>;
  onResult: (summary: string, priority: string) => void;
  onError: (message: string) => void;
  intervalMs?: number;
}

/** Periodically sample the camera and speak hazard summaries. */
export function startObstacleScanner(options: ScannerOptions): () => void {
  const interval = options.intervalMs ?? 4000;
  let stopped = false;
  let inFlight = false;

  const tick = async (): Promise<void> => {
    if (stopped || inFlight) return;
    const frame = options.capture();
    if (!frame) return;
    inFlight = true;
    try {
      const result = await options.detect(frame);
      if (!stopped) options.onResult(result.summary, result.priority);
    } catch (error) {
      if (!stopped) options.onError(error instanceof Error ? error.message : "Scan failed.");
    } finally {
      inFlight = false;
    }
  };

  const handle = window.setInterval(() => void tick(), interval);
  return () => {
    stopped = true;
    window.clearInterval(handle);
  };
}