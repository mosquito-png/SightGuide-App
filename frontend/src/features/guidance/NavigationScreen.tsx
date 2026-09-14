import { FormEvent, useEffect, useRef, useState } from "react";
import {
  getMapsConfig,
  getWalkingRoute,
  searchDestinationPlace,
  type NavigationRouteResponse,
  type PlaceSearchResult,
} from "../../core/api";
import {
  decodePolyline,
  getGoogleMaps,
  haversineMeters,
  loadGoogleMaps,
  type LatLng,
} from "../../core/maps";
import {
  clearDeviceLocationWatch,
  getDeviceLocation,
  requestLocationPermission,
  watchDeviceLocation,
  type DeviceLocation,
} from "../../voice/geolocation";
import { App } from "@capacitor/app";

export type NavPhase = "IDLE" | "DESTINATION_SELECTED" | "ROUTE_READY" | "NAVIGATING" | "ARRIVED";

/** Voice-requested destination, keyed so repeated requests re-trigger. */
export type NavigationHint = { key: number; query: string };

export type LocationStatus = "locating" | "active" | "unavailable" | "denied";

type NavigationScreenProps = {
  onListen: () => void;
  speak: (text: string) => void;
  destinationRequest: NavigationHint | null;
  onLocationStatus?: (status: LocationStatus) => void;
};

const ARRIVAL_RADIUS_METERS = 30;
const STEP_RADIUS_METERS = 20;

function formatError(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function providerLabel(provider: string): string {
  if (provider === "google_maps" || provider === "google_places") return "Google Maps";
  if (provider === "openstreetmap_osrm" || provider === "openstreetmap_nominatim") return "OpenStreetMap";
  return "Simulated preview";
}

const PHASE_LABEL: Record<NavPhase, string> = {
  IDLE: "Idle",
  DESTINATION_SELECTED: "Destination selected",
  ROUTE_READY: "Route ready",
  NAVIGATING: "Navigating",
  ARRIVED: "Arrived",
};

function getOSMEmbedUrl(current: LatLng | null, dest: PlaceSearchResult | null): string {
  const target = dest ? { lat: dest.lat, lng: dest.lng } : current ?? { lat: 28.6139, lng: 77.209 };
  const delta = dest ? 0.015 : 0.008;
  const bbox = `${target.lng - delta},${target.lat - delta},${target.lng + delta},${target.lat + delta}`;
  return `https://www.openstreetmap.org/export/embed.html?bbox=${encodeURIComponent(bbox)}&layer=mapnik&marker=${encodeURIComponent(`${target.lat},${target.lng}`)}`;
}

export function NavigationScreen({
  onListen,
  speak,
  destinationRequest,
  onLocationStatus,
}: NavigationScreenProps) {
  const [phase, setPhase] = useState<NavPhase>("IDLE");
  const [location, setLocation] = useState<LatLng | null>(null);
  const [locationStatus, setLocationStatus] = useState<LocationStatus>("locating");
  const [searchText, setSearchText] = useState("");
  const [destination, setDestination] = useState<PlaceSearchResult | null>(null);
  const [route, setRoute] = useState<NavigationRouteResponse | null>(null);
  const [resolving, setResolving] = useState(false);
  const [planning, setPlanning] = useState(false);
  const [error, setError] = useState("");
  const [mapsReady, setMapsReady] = useState(false);
  const [mapsError, setMapsError] = useState("");
  const [mapsNotice, setMapsNotice] = useState("");

  const mapRef = useRef<HTMLDivElement | null>(null);
  const searchBoxRef = useRef<HTMLInputElement | null>(null);
  const mapInstanceRef = useRef<any>(null);
  const currentMarkerRef = useRef<any>(null);
  const destinationMarkerRef = useRef<any>(null);
  const routePolylineRef = useRef<any>(null);
  const watchIdRef = useRef<string | number | null>(null);
  const mapIdRef = useRef<string>("");

  // Refs mirror the latest values so geolocation/watch callbacks stay accurate.
  const phaseRef = useRef<NavPhase>("IDLE");
  const locationRef = useRef<LatLng | null>(null);
  const destinationRef = useRef<PlaceSearchResult | null>(null);
  const routeRef = useRef<NavigationRouteResponse | null>(null);
  const pendingQueryRef = useRef<string | null>(null);
  const resolvingRef = useRef(false);
  const stepIndexRef = useRef(0);
  const speakRef = useRef(speak);
  const onLocationStatusRef = useRef(onLocationStatus);

  phaseRef.current = phase;
  destinationRef.current = destination;
  routeRef.current = route;
  speakRef.current = speak;
  onLocationStatusRef.current = onLocationStatus;

  // 1. Real GPS location: obtain and follow the user's position.
  useEffect(() => {
    let disposed = false;
    const handleLocation = (deviceLocation: DeviceLocation | null, locationError?: unknown) => {
      if (disposed) return;
      if (!deviceLocation) {
        const errorText = String(locationError ?? "").toLowerCase();
        const denied = errorText.includes("permission") || errorText.includes("denied") || errorText.includes("not allowed");
        setLocationStatus(denied ? "denied" : "unavailable");
        onLocationStatusRef.current?.(denied ? "denied" : "unavailable");
        setError(
          denied
            ? "Location permission was not granted. Grant GPS access to use walk navigation."
            : "Current location is unavailable right now.",
        );
        return;
      }
      const current: LatLng = { lat: deviceLocation.lat, lng: deviceLocation.lon };
      locationRef.current = current;
      setLocation(current);
      setLocationStatus("active");
      onLocationStatusRef.current?.("active");
      updateMarker(current);
      const currentPhase = phaseRef.current;
      if (currentPhase === "NAVIGATING") {
        handleMovement(current);
        panTo(current);
      } else if (currentPhase === "IDLE" || currentPhase === "DESTINATION_SELECTED") {
        panTo(current);
      }
      if (currentPhase !== "NAVIGATING" && currentPhase !== "ARRIVED" && pendingQueryRef.current) {
        const pending = pendingQueryRef.current;
        pendingQueryRef.current = null;
        void resolveDestination(pending);
      }
    };

    const startLocation = async () => {
      if (!(await requestLocationPermission())) {
        handleLocation(null, "permission denied");
        return;
      }
      const current = await getDeviceLocation(10000);
      handleLocation(current, current ? undefined : "location unavailable");
      if (disposed) return;
      watchIdRef.current = await watchDeviceLocation(handleLocation);
    };
    let disposedLifecycle = false;
    let appStateListener: { remove: () => Promise<void> } | null = null;
    void App.addListener("appStateChange", ({ isActive }) => {
      if (disposedLifecycle) return;
      if (!isActive) {
        void clearDeviceLocationWatch(watchIdRef.current);
        watchIdRef.current = null;
      } else if (watchIdRef.current === null) {
        void startLocation();
      }
    }).then((handle) => {
      if (disposedLifecycle) void handle.remove();
      else appStateListener = handle;
    });
    void startLocation();
    return () => {
      disposedLifecycle = true;
      void appStateListener?.remove();
      disposed = true;
      void clearDeviceLocationWatch(watchIdRef.current);
      watchIdRef.current = null;
    };
  }, []);

  const [mapProvider, setMapProvider] = useState<"google_maps" | "openstreetmap">("openstreetmap");

  // 2. Load Google Maps if configured; otherwise use live OpenStreetMap.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const config = await getMapsConfig();
        if (!config.configured || !config.api_key) {
          if (!cancelled) {
            setMapProvider("openstreetmap");
            setMapsReady(true);
            setMapsNotice("Using OpenStreetMap navigation (Add GOOGLE_MAPS_API_KEY to .env for Google Maps).");
          }
          return;
        }
        await loadGoogleMaps(config.api_key);
        if (cancelled) return;
        setMapProvider("google_maps");
        mapIdRef.current = config.map_id?.trim() ?? "";
        setMapsReady(true);
        initializeMap();
        if (locationRef.current) updateMarker(locationRef.current);
      } catch (err) {
        if (!cancelled) {
          console.warn("Google Maps load error, falling back to OpenStreetMap:", err);
          setMapProvider("openstreetmap");
          setMapsReady(true);
          setMapsError(formatError(err, "Google Maps failed to load."));
          setMapsNotice("Google Maps failed to load. Using OpenStreetMap navigation.");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // 3. Voice navigation request (existing voice pipeline) starts navigation.
  useEffect(() => {
    if (!destinationRequest || !destinationRequest.query) return;
    void resolveDestination(destinationRequest.query);
  }, [destinationRequest?.key]);

  function initializeMap() {
    const container = mapRef.current;
    const maps = getGoogleMaps();
    if (!container || !maps || mapInstanceRef.current) return;
    const options: any = {
      center: locationRef.current ?? { lat: 28.6139, lng: 77.209 },
      zoom: 16,
      mapTypeId: "roadmap",
      fullscreenControl: false,
      mapTypeControl: false,
      streetViewControl: false,
      zoomControl: true,
    };
    const mapId = mapIdRef.current;
    if (mapId) options.mapId = mapId;
    mapInstanceRef.current = new maps.Map(container, options);
  }

  function updateMarker(position: LatLng) {
    const maps = getGoogleMaps();
    if (!maps || !mapInstanceRef.current) return;
    const AdvancedMarker = mapIdRef.current ? maps.marker?.AdvancedMarkerElement : null;
    if (AdvancedMarker) {
      if (!currentMarkerRef.current) {
        const dot = document.createElement("div");
        dot.style.width = "18px";
        dot.style.height = "18px";
        dot.style.borderRadius = "50%";
        dot.style.background = "#4285f4";
        dot.style.border = "3px solid #ffffff";
        dot.style.boxShadow = "0 1px 4px rgba(0, 0, 0, 0.4)";
        currentMarkerRef.current = new AdvancedMarker({
          map: mapInstanceRef.current,
          position,
          title: "You are here",
          content: dot,
        });
      } else {
        currentMarkerRef.current.position = position;
      }
    } else {
      // Standard Marker fallback for standard Google Maps API keys without Map IDs
      if (!currentMarkerRef.current) {
        currentMarkerRef.current = new maps.Marker({
          map: mapInstanceRef.current,
          position,
          title: "You are here",
        });
      } else {
        currentMarkerRef.current.setPosition?.(position);
      }
    }
  }

  function markDestination(target: LatLng, title: string) {
    const maps = getGoogleMaps();
    if (!maps || !mapInstanceRef.current) return;
    const AdvancedMarker = mapIdRef.current ? maps.marker?.AdvancedMarkerElement : null;
    if (AdvancedMarker) {
      if (!destinationMarkerRef.current) {
        destinationMarkerRef.current = new AdvancedMarker({
          position: target,
          map: mapInstanceRef.current,
          title,
        });
      } else {
        destinationMarkerRef.current.position = target;
        destinationMarkerRef.current.title = title;
      }
    } else {
      // Standard Marker fallback
      if (!destinationMarkerRef.current) {
        destinationMarkerRef.current = new maps.Marker({
          position: target,
          map: mapInstanceRef.current,
          title,
        });
      } else {
        destinationMarkerRef.current.setPosition?.(target);
        destinationMarkerRef.current.setTitle?.(title);
      }
    }
  }

  function panTo(position: LatLng) {
    mapInstanceRef.current?.panTo(position);
  }

  function drawRoute(path: LatLng[]) {
    const maps = getGoogleMaps();
    if (!maps || !mapInstanceRef.current || path.length < 2) return;
    if (!routePolylineRef.current) {
      routePolylineRef.current = new maps.Polyline({
        path,
        map: mapInstanceRef.current,
        strokeColor: "#ffe171",
        strokeOpacity: 0.95,
        strokeWeight: 6,
      });
    } else {
      routePolylineRef.current.setPath(path);
    }
    const bounds = new maps.LatLngBounds();
    path.forEach((point) => bounds.extend(point));
    if (locationRef.current) bounds.extend(locationRef.current);
    mapInstanceRef.current.fitBounds(bounds);
  }

  function routePathFor(value: NavigationRouteResponse): LatLng[] {
    if (value.overview_polyline) return decodePolyline(value.overview_polyline);
    const path: LatLng[] = [];
    for (const step of value.steps) {
      if (step.start_lat != null && step.start_lng != null) path.push({ lat: step.start_lat, lng: step.start_lng });
      if (step.end_lat != null && step.end_lng != null) path.push({ lat: step.end_lat, lng: step.end_lng });
    }
    return path;
  }

  async function resolveDestination(query: string) {
    const trimmed = query.trim();
    if (!trimmed || resolvingRef.current) return;
    resolvingRef.current = true;
    setResolving(true);
    setError("");
    setSearchText(trimmed);
    setPhase("DESTINATION_SELECTED");
    const origin = locationRef.current;
    if (!origin) {
      pendingQueryRef.current = trimmed;
      setResolving(false);
      resolvingRef.current = false;
      return;
    }
    try {
      const result = await searchDestinationPlace(origin.lat, origin.lng, trimmed);
      setDestination(result);
      destinationRef.current = result;
      markDestination({ lat: result.lat, lng: result.lng }, result.name);
      panTo({ lat: result.lat, lng: result.lng });
      speakRef.current(
        `Destination selected: ${result.name}. ${result.distance_text}, about ${result.estimated_duration}.`,
      );
    } catch (err) {
      setDestination(null);
      destinationRef.current = null;
      setPhase("IDLE");
      setError(formatError(err, "Could not find a destination matching that request."));
    } finally {
      setResolving(false);
      resolvingRef.current = false;
    }
  }

  function handleSearchSubmit(event: FormEvent) {
    event.preventDefault();
    void resolveDestination(searchText);
  }

  async function planRoute() {
    const origin = locationRef.current;
    const dest = destinationRef.current;
    if (!origin) {
      setError("Waiting for GPS before planning the route.");
      return;
    }
    if (!dest) {
      setError("Select a destination first.");
      return;
    }
    setPlanning(true);
    setError("");
    try {
      const result = await getWalkingRoute(origin.lat, origin.lng, dest.name, dest.lat, dest.lng);
      setRoute(result);
      routeRef.current = result;
      setPhase("ROUTE_READY");
      drawRoute(routePathFor(result));
      const firstInstruction = result.steps.find((step) => step.maneuver !== "arrive")?.instruction;
      speakRef.current(
        `Route ready. ${result.total_distance}, about ${result.total_duration}. ${firstInstruction ?? result.summary}`,
      );
    } catch (err) {
      setPhase("DESTINATION_SELECTED");
      setError(formatError(err, "Could not calculate a route to that destination."));
    } finally {
      setPlanning(false);
    }
  }

  function startNavigation() {
    const current = routeRef.current;
    if (!current) return;
    setPhase("NAVIGATING");
    stepIndexRef.current = 0;
    const firstInstruction = current.steps.find((step) => step.maneuver !== "arrive")?.instruction;
    speakRef.current(firstInstruction ?? `Navigating to ${current.destination_name}. Follow the highlighted route.`);
  }

  function stopNavigation() {
    setPhase("IDLE");
    setRoute(null);
    routeRef.current = null;
    setDestination(null);
    destinationRef.current = null;
    stepIndexRef.current = 0;
    routePolylineRef.current?.setMap?.(null);
    routePolylineRef.current = null;
    if (destinationMarkerRef.current) destinationMarkerRef.current.map = null;
    destinationMarkerRef.current = null;
  }

  function handleMovement(position: LatLng) {
    const currentRoute = routeRef.current;
    const destinationNow = destinationRef.current;
    if (!currentRoute || !destinationNow) return;
    const arrivalMeters = haversineMeters(position, { lat: destinationNow.lat, lng: destinationNow.lng });
    if (arrivalMeters < ARRIVAL_RADIUS_METERS) {
      setPhase("ARRIVED");
      speakRef.current(`You have arrived at ${destinationNow.name}.`);
      return;
    }
    const steps = currentRoute.steps;
    if (steps.length === 0) return;
    let index = stepIndexRef.current;
    while (index < steps.length - 1) {
      const step = steps[index];
      const target =
        step.end_lat != null && step.end_lng != null ? { lat: step.end_lat, lng: step.end_lng } : null;
      if (target && haversineMeters(position, target) < STEP_RADIUS_METERS) index += 1;
      else break;
    }
    if (index !== stepIndexRef.current) {
      stepIndexRef.current = index;
      const step = steps[index];
      if (step?.maneuver !== "arrive" && step?.instruction) speakRef.current(step.instruction);
    }
  }

  // 4. Place search uses the backend search API (no legacy frontend autocomplete).

  const showLocationIssue = locationStatus === "denied" || locationStatus === "unavailable";

  return (
    <section className="feature-screen navigation-screen">
      <span className="eyebrow">Navigation</span>
      <h2>Where do you want to go?</h2>

      <div className="nav-status-row">
        <span className={`status-chip ${locationStatus === "active" ? "active" : ""}`}>
          <i />
          GPS {locationStatus === "active" ? "Active" : locationStatus === "locating" ? "Locating" : locationStatus === "denied" ? "Denied" : "Unavailable"}
        </span>
        <span className={`status-chip ${mapsReady ? "active" : ""}`}>
          <i />
          {mapProvider === "google_maps" ? "Google Maps" : "OpenStreetMap"}
        </span>
        <span className={`status-chip ${phase === "NAVIGATING" || phase === "ARRIVED" ? "active" : ""}`}>
          <i />
          {PHASE_LABEL[phase]}
        </span>
      </div>

      <form className="nav-search" onSubmit={handleSearchSubmit} role="search">
        <input
          ref={searchBoxRef}
          type="text"
          value={searchText}
          onChange={(event) => setSearchText(event.target.value)}
          placeholder="Search a destination or an address"
          aria-label="Destination search"
          autoComplete="off"
        />
        <button type="submit" disabled={resolving || !searchText.trim()}>
          {resolving ? "Searching…" : "Search"}
        </button>
        <button type="button" className="nav-speak-btn" onClick={onListen}>
          Speak
        </button>
      </form>

      {showLocationIssue ? (
        <div className="unavailable-panel nav-error">
          <strong>Location unavailable</strong>
          <span>{error || "Enable location access to search and navigate."}</span>
        </div>
      ) : null}
      {error && !showLocationIssue ? (
        <div className="unavailable-panel nav-error">
          <strong>Navigation notice</strong>
          <span>{error}</span>
        </div>
      ) : null}
      {mapsNotice ? (
        <div className="unavailable-panel nav-error nav-notice">
          <span>{mapsNotice}</span>
        </div>
      ) : null}

      <div className="nav-map" aria-label="Navigation map" style={{ minHeight: "320px", position: "relative" }}>
        {mapProvider === "openstreetmap" ? (
          <iframe
            title="OpenStreetMap Live Navigation"
            style={{ width: "100%", height: "100%", minHeight: "320px", border: 0, borderRadius: "16px" }}
            src={getOSMEmbedUrl(location, destination)}
            loading="lazy"
          />
        ) : (
          <>
            {!mapsReady && !mapsError ? (
              <div className="nav-map-placeholder">
                <strong>Loading map…</strong>
                <span>Google Maps is connecting.</span>
              </div>
            ) : null}
            {mapsError ? (
              <div className="nav-map-placeholder">
                <strong>Map unavailable</strong>
                <span>{mapsError}</span>
              </div>
            ) : null}
            {mapsReady && !location ? (
              <div className="nav-map-placeholder">
                <strong>Finding your location…</strong>
                <span>Waiting for GPS signal.</span>
              </div>
            ) : null}
            <div className="nav-map-canvas" ref={mapRef} />
          </>
        )}
      </div>

      {destination ? (
        <div className="nav-dest-card">
          <strong>{destination.name}</strong>
          <span>{destination.formatted_address}</span>
          {destination.distance_text ? (
            <div className="nav-route-meta">
              <span>{destination.distance_text}</span>
              <span>{destination.estimated_duration}</span>
            </div>
          ) : null}
        </div>
      ) : null}

      {route ? (
        <div className="nav-route-card">
          <strong>{route.destination_name}</strong>
          <div className="nav-route-meta">
            <span>{route.total_distance}</span>
            <span>{route.total_duration}</span>
            <span>{providerLabel(route.provider)}</span>
          </div>
          {route.provider === "simulated" ? (
            <p className="nav-route-note">Live routing was unavailable; this is a simulated preview.</p>
          ) : null}
          {route.steps.length > 0 ? (
            <ol className="nav-steps">
              {route.steps.map((step, index) => (
                <li key={`${step.instruction}-${index}`}>
                  <strong>{step.instruction}</strong>
                  <span>{step.distance_text} · {step.duration_text}</span>
                </li>
              ))}
            </ol>
          ) : null}
        </div>
      ) : null}

      <div className="nav-actions">
        {phase === "DESTINATION_SELECTED" && destination ? (
          <button className="primary-action" type="button" onClick={() => void planRoute()} disabled={planning}>
            {planning ? "Planning route…" : "Plan route"}
          </button>
        ) : null}
        {phase === "ROUTE_READY" ? (
          <button className="primary-action" type="button" onClick={startNavigation}>
            Start turn-by-turn
          </button>
        ) : null}
        {phase === "NAVIGATING" || phase === "ARRIVED" ? (
          <button className="critical-action" type="button" onClick={stopNavigation}>
            {phase === "ARRIVED" ? "New destination" : "End navigation"}
          </button>
        ) : null}
      </div>
    </section>
  );
}
