// Google Maps JavaScript API loader and small geometry helpers.
//
// The API key is never hard-coded in this file. It is fetched at runtime from
// the backend `/guidance/maps_config` endpoint, which is sourced from
// GOOGLE_MAPS_API_KEY in the backend environment file.

export type LatLng = { lat: number; lng: number };

type GoogleMapsNamespace = any;

declare global {
  interface Window {
    google?: { maps?: GoogleMapsNamespace };
  }
}

let loadPromise: Promise<GoogleMapsNamespace> | null = null;
let mapsScript: HTMLScriptElement | null = null;

export function getGoogleMaps(): GoogleMapsNamespace | null {
  return window.google?.maps ?? null;
}

export function loadGoogleMaps(apiKey: string): Promise<GoogleMapsNamespace> {
  const existing = getGoogleMaps();
  if (existing) return Promise.resolve(existing);
  if (loadPromise) return loadPromise;

  const callbackName = "__sightguide_maps_init";
  loadPromise = new Promise<GoogleMapsNamespace>((resolve, reject) => {
    let settled = false;
    let timeoutId: number | null = null;

    const finish = (fn: () => void) => {
      if (settled) return;
      settled = true;
      if (timeoutId !== null) window.clearTimeout(timeoutId);
      delete (window as any)[callbackName];
      loadPromise = null;
      fn();
    };

    (window as any)[callbackName] = () => {
      const maps = getGoogleMaps();
      if (maps) finish(() => resolve(maps));
      else finish(() => reject(new Error("Google Maps failed to initialize.")));
    };

    // Reuse a single script element across attempts: the Maps library is loaded
    // exactly once and the node is never removed from the DOM, so no two code
    // paths ever fight over removing the same element.
    const script = mapsScript ?? document.createElement("script");
    script.async = true;
    script.defer = true;
    script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(apiKey)}&libraries=marker&callback=${callbackName}`;
    script.onerror = () => {
      loadPromise = null;
      finish(() => reject(new Error("Google Maps could not be loaded.")));
    };

    if (!mapsScript) {
      mapsScript = script;
      document.head.appendChild(script);
    }

    timeoutId = window.setTimeout(() => {
      loadPromise = null;
      finish(() => reject(new Error("Google Maps failed to load in time.")));
    }, 8000);
  });
  return loadPromise;
}

/** Decode a Google-encoded polyline into latitude/longitude points. */
export function decodePolyline(encoded: string): LatLng[] {
  const points: LatLng[] = [];
  let index = 0;
  let lat = 0;
  let lng = 0;
  while (index < encoded.length) {
    let result = 0;
    let shift = 0;
    let b: number;
    do {
      b = encoded.charCodeAt(index++) - 63;
      result |= (b & 0x1f) << shift;
      shift += 5;
    } while (b >= 0x20);
    const deltaLat = (result & 1) !== 0 ? ~(result >> 1) : result >> 1;
    lat += deltaLat;

    result = 0;
    shift = 0;
    do {
      b = encoded.charCodeAt(index++) - 63;
      result |= (b & 0x1f) << shift;
      shift += 5;
    } while (b >= 0x20);
    const deltaLng = (result & 1) !== 0 ? ~(result >> 1) : result >> 1;
    lng += deltaLng;

    points.push({ lat: lat / 1e5, lng: lng / 1e5 });
  }
  return points;
}

/** Great-circle distance between two coordinates, in meters. */
export function haversineMeters(a: LatLng, b: LatLng): number {
  const radius = 6371000;
  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const p1 = toRad(a.lat);
  const p2 = toRad(b.lat);
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dLng / 2) ** 2;
  return radius * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
}