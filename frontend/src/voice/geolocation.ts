import { Capacitor } from "@capacitor/core";
import { Geolocation } from "@capacitor/geolocation";
import type { CallbackID } from "@capacitor/geolocation";
import { getFastNativeLocation } from "./telephony";

export interface DeviceLocation {
  lat: number;
  lon: number;
}

export type LocationCallback = (location: DeviceLocation | null, error?: unknown) => void;

const LAST_LOCATION_KEY = "sightguide.last_known_location";

let inMemoryLocation: DeviceLocation | null = (() => {
  try {
    const raw = typeof window !== "undefined" ? window.localStorage?.getItem(LAST_LOCATION_KEY) : null;
    if (raw) {
      const parsed = JSON.parse(raw);
      if (typeof parsed?.lat === "number" && typeof parsed?.lon === "number") {
        return parsed as DeviceLocation;
      }
    }
  } catch {
    /* storage unavailable */
  }
  return null;
})();

function saveLastKnownLocation(loc: DeviceLocation): void {
  inMemoryLocation = loc;
  try {
    window.localStorage?.setItem(LAST_LOCATION_KEY, JSON.stringify(loc));
  } catch {
    /* ignore */
  }
}

export function getLastKnownLocation(): DeviceLocation | null {
  return inMemoryLocation;
}

export async function requestLocationPermission(): Promise<boolean> {
  if (!Capacitor.isNativePlatform()) {
    return typeof navigator !== "undefined" && "geolocation" in navigator;
  }
  try {
    const permissions = await Geolocation.requestPermissions({ permissions: ["location"] });
    return permissions.location === "granted";
  } catch {
    return false;
  }
}

function toDeviceLocation(position: { coords: { latitude: number; longitude: number } }): DeviceLocation {
  const loc = { lat: position.coords.latitude, lon: position.coords.longitude };
  saveLastKnownLocation(loc);
  return loc;
}

/**
 * Resolve the device position with multi-tiered zero-failure fallback:
 * 1. Fast Native Android LocationManager (<10ms)
 * 2. Capacitor Geolocation / Web Geolocation
 * 3. Cached Last-Known GPS coordinates
 */
export async function getDeviceLocation(timeoutMs = 6000): Promise<DeviceLocation | null> {
  // 1. Try Fast Native Android Location First
  if (Capacitor.isNativePlatform()) {
    const fastLoc = await getFastNativeLocation();
    if (fastLoc && typeof fastLoc.lat === "number" && typeof fastLoc.lon === "number") {
      saveLastKnownLocation(fastLoc);
      return fastLoc;
    }
  }

  // 2. Try Capacitor Geolocation API
  if (Capacitor.isNativePlatform()) {
    try {
      const granted = await requestLocationPermission();
      if (granted) {
        const position = await Geolocation.getCurrentPosition({
          enableHighAccuracy: true,
          timeout: timeoutMs,
          maximumAge: 10000,
          enableLocationFallback: true,
        });
        if (position?.coords) {
          return toDeviceLocation(position);
        }
      }
    } catch (err) {
      console.warn("Capacitor getCurrentPosition failed:", err);
    }
  }

  // 3. Try standard Web navigator.geolocation
  if (typeof navigator !== "undefined" && "geolocation" in navigator) {
    try {
      const webPos = await new Promise<DeviceLocation | null>((resolve) => {
        navigator.geolocation.getCurrentPosition(
          (pos) => {
            const loc = { lat: pos.coords.latitude, lon: pos.coords.longitude };
            saveLastKnownLocation(loc);
            resolve(loc);
          },
          () => resolve(null),
          { enableHighAccuracy: true, timeout: timeoutMs, maximumAge: 10000 },
        );
      });
      if (webPos) return webPos;
    } catch {
      /* ignore */
    }
  }

  // 4. Ultimate Fallback: Return Last-Known Location if fresh fix couldn't be obtained in time
  const cached = getLastKnownLocation();
  if (cached) {
    console.info("Using cached last-known location:", cached);
    return cached;
  }

  return null;
}

export async function watchDeviceLocation(callback: LocationCallback): Promise<CallbackID | number | null> {
  if (Capacitor.isNativePlatform()) {
    try {
      return await Geolocation.watchPosition(
        {
          enableHighAccuracy: true,
          timeout: 15000,
          maximumAge: 5000,
          minimumUpdateInterval: 5000,
          interval: 5000,
          enableLocationFallback: true,
        },
        (position, error) => {
          if (position?.coords) {
            const loc = toDeviceLocation(position);
            callback(loc, error);
          } else {
            callback(null, error);
          }
        },
      );
    } catch (error) {
      callback(null, error);
      return null;
    }
  }
  if (typeof navigator === "undefined" || !("geolocation" in navigator)) return null;
  return navigator.geolocation.watchPosition(
    (position) => {
      const loc = toDeviceLocation(position);
      callback(loc);
    },
    (error) => callback(null, error),
    { enableHighAccuracy: true, timeout: 15000, maximumAge: 5000 },
  );
}

export async function clearDeviceLocationWatch(watchId: CallbackID | number | null): Promise<void> {
  if (watchId === null) return;
  if (Capacitor.isNativePlatform()) {
    await Geolocation.clearWatch({ id: String(watchId) });
    return;
  }
  if (typeof navigator !== "undefined" && "geolocation" in navigator) {
    navigator.geolocation.clearWatch(watchId as number);
  }
}
