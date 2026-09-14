import { Capacitor } from "@capacitor/core";

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(message: string, status = 0, code = "API_ERROR") {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

const STORAGE_API_KEY = "sightguide.api_url";
export const DEFAULT_PRODUCTION_API_URL = "https://web-production-e7691.up.railway.app/api";

export function getCustomApiBaseUrl(): string | null {
  try {
    const saved = window.localStorage?.getItem(STORAGE_API_KEY) || null;
    // On native mobile, if an old localhost URL was previously stored during USB testing,
    // clear it so the app seamlessly connects to the production cloud backend.
    if (Capacitor.isNativePlatform() && saved && (saved.includes("localhost") || saved.includes("127.0.0.1"))) {
      window.localStorage?.removeItem(STORAGE_API_KEY);
      return null;
    }
    return saved;
  } catch {
    return null;
  }
}

export function setCustomApiBaseUrl(url: string): void {
  try {
    const trimmed = url.trim().replace(/\/+$/, "");
    if (trimmed) {
      window.localStorage?.setItem(STORAGE_API_KEY, trimmed);
    } else {
      window.localStorage?.removeItem(STORAGE_API_KEY);
    }
  } catch {
    /* storage unavailable */
  }
}

export function normalizeApiBaseUrl(value?: string): string {
  const saved = getCustomApiBaseUrl();
  if (saved) return saved;

  const envValue = (value ?? "").trim();
  if (envValue) return envValue.replace(/\/+$/, "");

  // Native Android uses the production Railway cloud backend by default
  if (Capacitor.isNativePlatform()) {
    return DEFAULT_PRODUCTION_API_URL;
  }

  // When running in browser / dev server, use relative path `/api` so Vite proxy seamlessly handles HTTPS & WSS
  return "/api";
}

export function getApiBaseUrl(): string {
  return normalizeApiBaseUrl(import.meta.env.VITE_API_URL || DEFAULT_PRODUCTION_API_URL);
}

export const apiBaseUrl = getApiBaseUrl();

export function buildApiUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const base = getApiBaseUrl();
  if (base.endsWith("/api") && normalizedPath.startsWith("/api")) {
    return `${base}${normalizedPath.slice(4)}`;
  }
  return `${base}${normalizedPath}`;
}

export interface FetchWithTimeoutOptions extends RequestInit {
  timeoutMs?: number;
  retries?: number;
}

/**
 * Robust fetch wrapper with configurable timeout, automatic retry on transient
 * network failures, offline detection, and clear error translation for mobile.
 */
export async function fetchWithTimeoutAndRetry(
  url: string,
  options: FetchWithTimeoutOptions = {},
): Promise<Response> {
  const { timeoutMs = 15000, retries = 1, ...fetchOptions } = options;

  if (typeof navigator !== "undefined" && navigator.onLine === false) {
    throw new ApiError("No internet connection. Please check your network.", 0, "OFFLINE");
  }

  let attempt = 0;
  while (true) {
    attempt += 1;
    const controller = new AbortController();
    let timedOut = false;
    const timeoutHandle = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs);

    const externalSignal = options.signal;
    const onExternalAbort = () => controller.abort();
    if (externalSignal) {
      if (externalSignal.aborted) {
        window.clearTimeout(timeoutHandle);
        throw new ApiError("Request was cancelled.", 0, "ABORTED");
      }
      externalSignal.addEventListener("abort", onExternalAbort);
    }

    try {
      const response = await fetch(url, {
        ...fetchOptions,
        signal: controller.signal,
      });
      window.clearTimeout(timeoutHandle);
      if (externalSignal) externalSignal.removeEventListener("abort", onExternalAbort);
      return response;
    } catch (err: unknown) {
      window.clearTimeout(timeoutHandle);
      if (externalSignal) externalSignal.removeEventListener("abort", onExternalAbort);

      if (timedOut) {
        if (attempt <= retries) {
          await new Promise((resolve) => window.setTimeout(resolve, 800 * attempt));
          continue;
        }
        throw new ApiError("The server took too long to respond. Please try again.", 408, "TIMEOUT");
      }

      if (externalSignal?.aborted || (err as { name?: string })?.name === "AbortError") {
        throw new ApiError("Request was cancelled.", 0, "ABORTED");
      }

      if (attempt <= retries) {
        await new Promise((resolve) => window.setTimeout(resolve, 800 * attempt));
        continue;
      }

      throw new ApiError(
        "Unable to connect to SightGuide server. Check your network or server URL in Settings.",
        0,
        "NETWORK_ERROR",
      );
    }
  }
}

// In-flight request deduplication map to prevent repeated parallel API calls
const inFlightRequests = new Map<string, Promise<any>>();

function deduplicate<T>(key: string, producer: () => Promise<T>): Promise<T> {
  const existing = inFlightRequests.get(key);
  if (existing) return existing as Promise<T>;

  const promise = producer().finally(() => {
    inFlightRequests.delete(key);
  });
  inFlightRequests.set(key, promise);
  return promise;
}

export type GuidanceResponse = {
  message: string;
  priority: string;
};

export type DetectedObstacle = {
  label: string;
  location_clock: string;
  distance: string;
  hazard_level: "low" | "medium" | "urgent";
};

export type VisionDetectionResponse = {
  summary: string;
  obstacles: DetectedObstacle[];
  priority: "normal" | "warning" | "urgent";
  extracted_text?: string;
  timestamp?: string;
};

export type VoiceAssistantQueryResponse = {
  answer: string;
  action: "speak" | "start_scan" | "stop_scan" | "switch_camera" | "mute" | "start_navigation" | "read_text";
  priority: "normal" | "warning" | "urgent";
  detected_items?: string[];
  extracted_text?: string;
  navigation_destination?: string;
  timestamp?: string;
};

export type OCRReadTextResponse = {
  text: string;
  summary: string;
  reading_type: "product_label" | "sign" | "document" | "handwriting" | "screen" | "general";
  priority: "normal" | "warning" | "urgent";
  timestamp?: string;
};

export type NavigationStep = {
  instruction: string;
  distance_text: string;
  distance_meters: number;
  duration_text: string;
  maneuver: string;
  start_lat?: number;
  start_lng?: number;
  end_lat?: number;
  end_lng?: number;
};

export type NavigationRouteResponse = {
  destination_name: string;
  total_distance: string;
  total_duration: string;
  summary: string;
  steps: NavigationStep[];
  overview_polyline?: string | null;
  provider: "google_maps" | "openstreetmap_osrm" | "simulated";
  timestamp?: string;
};

export async function describeScene(scene: string, signal?: AbortSignal): Promise<GuidanceResponse> {
  const response = await fetchWithTimeoutAndRetry(buildApiUrl("/guidance/describe"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scene }),
    signal,
    timeoutMs: 15000,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    const msg = errorData?.error?.message || errorData?.detail || "The guidance service is unavailable.";
    throw new ApiError(msg, response.status);
  }

  return response.json() as Promise<GuidanceResponse>;
}

export async function detectObstacles(
  imageBase64: string,
  mode: string = "navigation",
  promptOverride?: string | unknown,
  signal?: AbortSignal,
): Promise<VisionDetectionResponse> {
  const cleanMode = typeof mode === "string" ? mode : "navigation";
  const cleanPrompt = typeof promptOverride === "string" ? promptOverride : null;
  const dedupeKey = `detect:${imageBase64.slice(-64)}:${cleanMode}`;
  return deduplicate(dedupeKey, async () => {
    const response = await fetchWithTimeoutAndRetry(buildApiUrl("/guidance/detect"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        image_base64: imageBase64,
        mode: cleanMode,
        prompt_override: cleanPrompt,
      }),
      signal,
      timeoutMs: 18000,
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => null);
      const msg = errorData?.error?.message || errorData?.detail || "Obstacle detection request failed.";
      throw new ApiError(msg, response.status);
    }

    return response.json() as Promise<VisionDetectionResponse>;
  });
}

export async function askVoiceAssistant(
  question: string,
  imageBase64?: string | null,
  context: string = "general",
  signal?: AbortSignal,
): Promise<VoiceAssistantQueryResponse> {
  const response = await fetchWithTimeoutAndRetry(buildApiUrl("/guidance/ask"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      image_base64: imageBase64 || null,
      context,
    }),
    signal,
    timeoutMs: 16000,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    const msg = errorData?.error?.message || errorData?.detail || "Voice assistant request failed.";
    throw new ApiError(msg, response.status);
  }

  return response.json() as Promise<VoiceAssistantQueryResponse>;
}

export async function getWalkingRoute(
  originLat: number,
  originLng: number,
  destination: string,
  destinationLat?: number,
  destinationLng?: number,
  signal?: AbortSignal,
): Promise<NavigationRouteResponse> {
  const dedupeKey = `route:${originLat.toFixed(4)},${originLng.toFixed(4)}:${destination}`;
  return deduplicate(dedupeKey, async () => {
    const response = await fetchWithTimeoutAndRetry(buildApiUrl("/guidance/route"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        origin_lat: originLat,
        origin_lng: originLng,
        destination,
        destination_lat: destinationLat || null,
        destination_lng: destinationLng || null,
      }),
      signal,
      timeoutMs: 10000,
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => null);
      const msg = errorData?.error?.message || errorData?.detail || "Could not calculate walking route.";
      throw new ApiError(msg, response.status);
    }

    return response.json() as Promise<NavigationRouteResponse>;
  });
}

export type PlaceSearchResult = {
  name: string;
  formatted_address: string;
  lat: number;
  lng: number;
  distance_text: string;
  distance_meters: number;
  estimated_duration: string;
  provider: "google_places" | "openstreetmap_nominatim";
  timestamp?: string;
};

export async function searchDestinationPlace(
  originLat: number,
  originLng: number,
  query: string,
  signal?: AbortSignal,
): Promise<PlaceSearchResult> {
  const dedupeKey = `place:${query.trim().toLowerCase()}`;
  return deduplicate(dedupeKey, async () => {
    const response = await fetchWithTimeoutAndRetry(buildApiUrl("/guidance/search_place"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        origin_lat: originLat,
        origin_lng: originLng,
        query,
      }),
      signal,
      timeoutMs: 10000,
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => null);
      const msg = errorData?.error?.message || errorData?.detail || "Could not find destination place.";
      throw new ApiError(msg, response.status);
    }

    return response.json() as Promise<PlaceSearchResult>;
  });
}

export async function readTextFromImage(
  imageBase64: string,
  focusArea?: string | unknown,
  promptOverride?: string | unknown,
  signal?: AbortSignal,
): Promise<OCRReadTextResponse> {
  const cleanPrompt = typeof promptOverride === "string" ? promptOverride : null;
  const cleanFocus = typeof focusArea === "string" ? focusArea : null;
  const dedupeKey = `ocr:${imageBase64.slice(-64)}`;
  return deduplicate(dedupeKey, async () => {
    const response = await fetchWithTimeoutAndRetry(buildApiUrl("/guidance/read_text"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        image_base64: imageBase64,
        focus_area: cleanFocus,
        prompt_override: cleanPrompt,
      }),
      signal,
      timeoutMs: 20000,
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => null);
      const msg = errorData?.error?.message || errorData?.detail || "Reading text from image failed.";
      throw new ApiError(msg, response.status);
    }

    return response.json() as Promise<OCRReadTextResponse>;
  });
}

export type MapsConfigResponse = {
  configured: boolean;
  api_key?: string | null;
  map_id?: string | null;
};

export type MapsConfig = MapsConfigResponse;

export async function getMapsConfig(): Promise<MapsConfigResponse> {
  try {
    const response = await fetchWithTimeoutAndRetry(buildApiUrl("/guidance/maps_config"), { timeoutMs: 6000 });
    if (!response.ok) return { configured: false };
    return response.json() as Promise<MapsConfigResponse>;
  } catch {
    return { configured: false };
  }
}

export type ConversationTurn = {
  role: "user" | "assistant";
  text: string;
};

export type DeviceDirective = {
  action: string;
  value?: string | null;
  parameters?: Record<string, unknown>;
};

export type VoiceCommandResponse = {
  intent: string;
  text: string;
  priority: "normal" | "warning" | "urgent";
  action: string;
  directives: DeviceDirective[];
  needs_frame: boolean;
  navigation_destination?: string | null;
  detected_items?: string[];
  extracted_text?: string | null;
  timestamp?: string | null;
};

export async function sendVoiceCommand(
  text: string,
  options: {
    context?: ConversationTurn[];
    lat?: number | null;
    lon?: number | null;
    imageBase64?: string | null;
    signal?: AbortSignal;
  } = {},
): Promise<VoiceCommandResponse> {
  const response = await fetchWithTimeoutAndRetry(buildApiUrl("/voice/command"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text,
      context: options.context ?? [],
      lat: options.lat ?? null,
      lon: options.lon ?? null,
      image_base64: options.imageBase64 ?? null,
    }),
    signal: options.signal,
    timeoutMs: 16000,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    const msg = errorData?.error?.message || errorData?.detail || "The voice assistant could not be reached.";
    throw new ApiError(msg, response.status);
  }

  return response.json() as Promise<VoiceCommandResponse>;
}

export function openVoiceSocket(): WebSocket {
  const baseUrl = getApiBaseUrl();
  const url = new URL(baseUrl, typeof window !== "undefined" ? window.location.href : "http://localhost:8000");
  const isLocalHost = Boolean(url.hostname.match(/^(localhost|127\.0\.0\.1|10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[0-1])\.)/));

  if (
    !Capacitor.isNativePlatform() &&
    !isLocalHost &&
    typeof window !== "undefined" &&
    window.location.protocol === "https:" &&
    url.protocol !== "https:"
  ) {
    throw new Error("Voice WebSocket requires a secure wss:// backend when the app is loaded over HTTPS.");
  }

  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  const path = url.pathname.replace(/\/+$/, "");
  url.pathname = path.endsWith("/api") ? `${path}/voice/ws` : `${path}/api/voice/ws`;
  url.search = "";
  url.hash = "";
  return new WebSocket(url.toString());
}

