from pydantic import BaseModel, Field


class GuidanceRequest(BaseModel):
    scene: str = Field(min_length=1, max_length=2000)


class GuidanceResponse(BaseModel):
    message: str
    priority: str = "normal"


class DetectedObstacle(BaseModel):
    label: str
    location_clock: str = "12 o'clock"
    distance: str = "nearby"
    hazard_level: str = "low"  # low, medium, urgent


class VisionDetectionRequest(BaseModel):
    image_base64: str = Field(min_length=10, description="Base64 encoded JPEG/PNG camera frame")
    mode: str = Field(default="navigation", description="Detection mode: navigation, obstacle, reading")
    prompt_override: str | None = None


class VisionDetectionResponse(BaseModel):
    summary: str
    obstacles: list[DetectedObstacle] = Field(default_factory=list)
    priority: str = "normal"  # normal, warning, urgent
    extracted_text: str | None = None
    timestamp: str | None = None


class VoiceAssistantQueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000, description="Voice command or question from blind user")
    image_base64: str | None = Field(default=None, description="Optional base64 image frame from camera")
    context: str | None = Field(default="general", description="Context: hand_object, surroundings, room_nav, street_nav, reading, ocr")


class VoiceAssistantQueryResponse(BaseModel):
    answer: str
    action: str = "speak"  # speak, start_scan, stop_scan, switch_camera, mute, start_navigation, read_text
    priority: str = "normal"  # normal, warning, urgent
    detected_items: list[str] = Field(default_factory=list)
    extracted_text: str | None = None
    navigation_destination: str | None = None
    timestamp: str | None = None


class OCRReadTextRequest(BaseModel):
    image_base64: str = Field(min_length=10, description="Base64 encoded JPEG/PNG image to read text from")
    focus_area: str | None = Field(default=None, description="Optional focus area e.g. label, sign, document, screen")
    prompt_override: str | None = None


class OCRReadTextResponse(BaseModel):
    text: str = Field(description="Full extracted verbatim text from the image")
    summary: str = Field(description="Natural spoken summary of what is written")
    reading_type: str = Field(default="general", description="Type: product_label, sign, document, handwriting, screen, general")
    priority: str = "normal"  # normal, warning, urgent
    timestamp: str | None = None


class NavigationStep(BaseModel):
    instruction: str
    distance_text: str
    distance_meters: float
    duration_text: str
    maneuver: str = "straight"  # straight, turn-left, turn-right, u-turn, arrive
    start_lat: float | None = None
    start_lng: float | None = None
    end_lat: float | None = None
    end_lng: float | None = None


class NavigationRouteRequest(BaseModel):
    origin_lat: float = Field(description="User's current GPS latitude")
    origin_lng: float = Field(description="User's current GPS longitude")
    destination: str = Field(min_length=1, max_length=500, description="Destination name or address")
    destination_lat: float | None = None
    destination_lng: float | None = None


class NavigationRouteResponse(BaseModel):
    destination_name: str
    total_distance: str
    total_duration: str
    summary: str
    steps: list[NavigationStep] = Field(default_factory=list)
    overview_polyline: str | None = Field(default=None, description="Google-encoded polyline used to draw the route on a map")
    provider: str = "google_maps"  # google_maps | openstreetmap_osrm | simulated
    timestamp: str | None = None


class PlaceSearchRequest(BaseModel):
    origin_lat: float = Field(description="User current GPS latitude")
    origin_lng: float = Field(description="User current GPS longitude")
    query: str = Field(min_length=1, max_length=500, description="Destination place or address search query")


class PlaceSearchResult(BaseModel):
    name: str
    formatted_address: str
    lat: float
    lng: float
    distance_text: str
    distance_meters: float
    estimated_duration: str
    provider: str = "google_places"  # google_places | openstreetmap_nominatim
    timestamp: str | None = None


class MapsConfigResponse(BaseModel):
    """Whether Google Maps is configured and, if so, the client-side API key.

    The key is read from ``GOOGLE_MAPS_API_KEY`` (environment/.env) — it is
    never hard-coded and must never be written to logs. It is returned to the
    browser only so the Google Maps JavaScript API can be loaded at runtime.
    """

    configured: bool
    api_key: str | None = None
    map_id: str | None = None




