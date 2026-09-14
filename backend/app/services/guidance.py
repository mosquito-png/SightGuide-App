from datetime import datetime, timezone
import base64
import io
import html
import json
import math
import os
import re
import time
import urllib.parse
import logging

import httpx

logger = logging.getLogger(__name__)

from app.core.config import settings

from app.schemas.guidance import (
    DetectedObstacle,
    GuidanceResponse,
    NavigationRouteResponse,
    NavigationStep,
    OCRReadTextResponse,
    PlaceSearchResult,
    VisionDetectionResponse,
    VoiceAssistantQueryResponse,
)

from app.ai.providers import (
    FallbackLanguageModel,
    GeminiLanguageModel,
    LanguageModel,
    OpenAILanguageModel,
    get_default_language_model,
)


NAVIGATION_INTENT_PATTERN = re.compile(
    r"(?:"
    r"navigate(?:\s+to)?|"
    r"take\s+me\s+to|"
    r"walk\s+to|"
    r"directions\s+to|"
    r"route\s+to|"
    r"how\s+(?:do\s+i|can\s+i|to)\s+(?:get|walk|go|reach)\s+to|"
    r"go\s+to|"
    r"set\s+(?:the\s+)?destination\s+(?:to|as)|"
    r"change\s+destination\s+to|"
    r"destination\s+(?:to|is)|"
    r"find\s+(?:the\s+)?nearest|"
    r"where\s+is\s+(?:the\s+)?nearest|"
    r"guide\s+me\s+to|"
    r"take\s+me\s+towards|"
    r"head\s+to|"
    r"search\s+for\s+(?:the\s+)?nearest|"
    r"nearest|"
    r"closest"
    r")\s+(.+)",
    re.IGNORECASE,
)


# Google Maps replies with a misleading HTTP 200 even when the key is
# disabled, billing is off, or the legacy endpoint is unavailable. These
# responses are useless (no data) but cost several seconds of network time
# before we fall back to OpenStreetMap. Once we detect one, we flag Google as
# unusable for the rest of the process so subsequent requests skip straight to
# the OSM fallback and stay fast.
_GOOGLE_UNUSABLE = False

_GOOGLE_FAILURE_MARKERS = (
    "REQUEST_DENIED",
    "OVER_QUERY_LIMIT",
    "INVALID_REQUEST",
    "not enabled",
    "legacy api",
    "enable billing",
    "billing on the google cloud",
    "api key not valid",
    "requestor has exceeded",
)


def _google_responded_unusable(data) -> bool:
    """True when a Google API response carries no usable data for us.

    Handles both the ``status`` field (e.g. ``REQUEST_DENIED``) and the
    human-readable ``error_message`` (billing / legacy-API / invalid-key).
    """
    if data is None:
        return True
    status = str(data.get("status", "")).upper()
    if status in {"REQUEST_DENIED", "OVER_QUERY_LIMIT", "INVALID_REQUEST", "ZERO_RESULTS"}:
        return True
    text = (data.get("error_message") or "").lower()
    return any(marker in text for marker in _GOOGLE_FAILURE_MARKERS)


def _mark_google_unusable_if_needed(data) -> None:
    global _GOOGLE_UNUSABLE
    if _google_responded_unusable(data):
        _GOOGLE_UNUSABLE = True


def _google_available() -> bool:
    return bool(settings.google_maps_api_key) and not _GOOGLE_UNUSABLE


# ---- Small TTL caches so repeat navigations avoid slow external lookups ----
# Nominatim and OSRM can each take several seconds. Destinations/routes are
# commonly revisited, so we cache geocoded coordinates and OSRM route JSON
# for a short window. The cache is process-local (fine for a single-frontend
# deployment) and bounded to avoid unbounded growth.
_CACHE_TTL_SECONDS = 3600  # 1 hour
_GEOCODE_CACHE: dict[str, tuple[float, float, str, float]] = {}
# key: (origin_lat, origin_lng, dest_lat, dest_lng) -> (expires_at, osrm_json)
_OSRM_CACHE: dict[tuple[float, float, float, float], tuple[float, dict]] = {}

_YOLO_MODEL = None
_YOLO_MODEL_NAME = os.getenv("YOLO_MODEL", "yolov8n.pt")
_YOLO_LOAD_FAILURE: str | None = None

_COCO_HAZARD_LABELS = {
    "person",
    "bicycle",
    "car",
    "motorcycle",
    "bus",
    "truck",
    "bench",
    "chair",
    "couch",
    "potted plant",
    "traffic light",
    "stop sign",
    "bird",
    "cat",
    "dog",
}


def _cache_get(cache: dict, key) -> object | None:
    item = cache.get(key)
    if item is None:
        return None
    if item[0] < time.monotonic():
        cache.pop(key, None)
        return None
    return item[1]


def _osrm_route_lookup_cached(
    origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float
) -> dict | None:
    """Return a cached OSRM route dict for a coordinate pair, or None on miss."""
    key = (round(origin_lat, 6), round(origin_lng, 6), round(dest_lat, 6), round(dest_lng, 6))
    return _cache_get(_OSRM_CACHE, key)


def _cache_osrm_route(
    origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float, data: dict
) -> None:
    key = (round(origin_lat, 6), round(origin_lng, 6), round(dest_lat, 6), round(dest_lng, 6))
    if len(_OSRM_CACHE) > 256:
        _OSRM_CACHE.clear()
    _OSRM_CACHE[key] = (time.monotonic() + _CACHE_TTL_SECONDS, data)


def _geocode_lookup_cached(destination: str) -> tuple[float, float, str] | None:
    """Return a cached geocode (lat, lng, short name) for a query, or None on miss."""
    key = destination.strip().lower()
    cached = _cache_get(_GEOCODE_CACHE, key)
    if cached is not None:
        return cached
    return None


def _cache_geocode(destination: str, lat: float, lng: float, name: str) -> None:
    key = destination.strip().lower()
    if len(_GEOCODE_CACHE) > 512:
        _GEOCODE_CACHE.clear()
    _GEOCODE_CACHE[key] = (time.monotonic() + _CACHE_TTL_SECONDS, (lat, lng, name))


def _load_yolo_model():
    """Lazily load the YOLO weights.

    The import is deferred so the API still boots (and falls back to the Gemini
    vision path) when the optional ``ultralytics`` dependency is unavailable.
    """
    global _YOLO_MODEL, _YOLO_LOAD_FAILURE
    if _YOLO_MODEL is not None:
        return _YOLO_MODEL
    if _YOLO_LOAD_FAILURE is not None:
        raise RuntimeError(_YOLO_LOAD_FAILURE)
    try:
        from ultralytics import YOLO
    except Exception as error:  # noqa: BLE001 - report the first load failure once
        _YOLO_LOAD_FAILURE = f"YOLO is not available: {error}"
        raise RuntimeError(_YOLO_LOAD_FAILURE) from error
    try:
        _YOLO_MODEL = YOLO(_YOLO_MODEL_NAME)
    except Exception as error:
        _YOLO_LOAD_FAILURE = f"YOLO model could not be loaded: {error}"
        raise RuntimeError(_YOLO_LOAD_FAILURE) from error
    return _YOLO_MODEL


def _decode_base64_image(image_base64: str):
    try:
        import numpy as np
        from PIL import Image
    except ImportError as error:
        raise RuntimeError(f"Image processing libraries are not available: {error}") from error
    payload = image_base64.strip()
    if "," in payload and payload.lower().startswith("data:"):
        payload = payload.split(",", 1)[1]
    image_bytes = base64.b64decode(payload)
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    return np.array(image)


def _clock_position_from_box(x_center: float, image_width: int) -> str:
    if image_width <= 0:
        return "12 o'clock"
    ratio = x_center / image_width
    if ratio < 0.166:
        return "9 o'clock"
    if ratio < 0.333:
        return "10 o'clock"
    if ratio < 0.5:
        return "11 o'clock"
    if ratio < 0.666:
        return "1 o'clock"
    if ratio < 0.833:
        return "2 o'clock"
    return "3 o'clock"


def _distance_text_from_box(box_width: float, box_height: float, image_width: int, image_height: int) -> str:
    if image_width <= 0 or image_height <= 0:
        return "nearby"
    area_ratio = max((box_width * box_height) / float(image_width * image_height), 1e-6)
    if area_ratio >= 0.20:
        return "very close"
    if area_ratio >= 0.08:
        return "close"
    if area_ratio >= 0.02:
        return "a few meters away"
    return "far"


def _priority_from_labels(obstacles: list[DetectedObstacle]) -> str:
    if any(obs.hazard_level == "urgent" for obs in obstacles):
        return "urgent"
    if any(obs.hazard_level == "medium" for obs in obstacles):
        return "warning"
    return "normal"


def _scalar(value) -> float:
    if hasattr(value, "item"):
        return float(value.item())
    return float(value)


def _clean_spoken_answer(answer: str, user_text: str | None = None) -> str:
    cleaned = " ".join((answer or "").strip().split())
    if not cleaned:
        return cleaned

    lowered = cleaned.lower()
    if user_text:
        user_lower = " ".join(user_text.strip().split()).lower()
        if lowered == user_lower:
            return ""
        if lowered.startswith(user_lower):
            cleaned = cleaned[len(user_text.strip()):].lstrip(" :-")
            cleaned = " ".join(cleaned.split())

    echo_prefixes = (
        "the user asks:",
        "you asked:",
        "you said:",
        "request:",
        "question:",
    )
    for prefix in echo_prefixes:
        if lowered.startswith(prefix):
            cleaned = cleaned.split(":", 1)[-1].strip() if ":" in cleaned else cleaned[len(prefix):].strip()
            cleaned = " ".join(cleaned.split())
            lowered = cleaned.lower()

    if cleaned.startswith(("\"","'")) and cleaned.endswith(("\"","'")) and len(cleaned) > 1:
        cleaned = cleaned[1:-1].strip()
    return cleaned


def _token_set(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9']+", text.lower()) if len(token) > 2}


def _is_echo(answer: str, user_text: str) -> bool:
    answer_tokens = _token_set(answer)
    user_tokens = _token_set(user_text)
    if not answer_tokens or not user_tokens:
        return False
    overlap = len(answer_tokens & user_tokens) / max(len(user_tokens), 1)
    return overlap >= 0.8


def _fallback_voice_answer(question: str) -> str:
    lower_q = question.lower()
    if any(phrase in lower_q for phrase in ["what is in my hand", "what am i holding", "read label", "what is this"]):
        return "I’m checking what you’re holding."
    if any(phrase in lower_q for phrase in ["what do you see", "describe", "surroundings", "what is around me"]):
        return "I’m checking your surroundings now."
    if any(phrase in lower_q for phrase in ["where is", "navigate", "walk to", "take me to", "directions"]):
        return "I’m working out the route or location now."
    return "I’m here to help."



def extract_navigation_destination(text: str) -> str | None:
    """Return the destination named in a navigation voice intent, else None.

    Shared by the voice assistant endpoint and the live voice WebSocket
    pipeline so that "Navigate to X" / "Take me to the nearest Y" pass
    through the same intent routing.
    """
    if not text:
        return None
    match = NAVIGATION_INTENT_PATTERN.search(text.strip())
    if not match:
        return None
    destination = match.group(1).strip().strip("?.! ")
    return destination or None


def _haversine_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two coordinates, in meters."""
    radius = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = math.sin(d_lat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(d_lng / 2) ** 2
    return float(radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


async def describe_scene(scene: str, model: LanguageModel | None = None) -> GuidanceResponse:
    normalized_scene = scene.strip()
    if not normalized_scene:
        raise ValueError("scene must not be empty")
    prompt = (
        "You are SightGuide, an accessibility vision assistant for visually impaired people.\n"
        "Provide a comprehensive, vivid, spoken description of the entire scene described below.\n"
        "Describe the full environment, all objects, people, spatial relationships, and conditions in detail so the user can visualize the entire scene.\n"
        "Do not repeat or quote the user's words, and do not mention 'the user asked'.\n"
        "Respond with only the spoken answer.\n\n"
        f"Scene: {normalized_scene}"
    )
    generated = await (model or get_default_language_model()).complete(prompt)
    return GuidanceResponse(
        message=_clean_spoken_answer(generated, normalized_scene) or generated,
        priority="normal",
    )


_query_cache: dict[str, tuple[float, VoiceAssistantQueryResponse]] = {}
_ocr_cache: dict[str, tuple[float, OCRReadTextResponse]] = {}
_CACHE_TTL_SECONDS = 5.0


def _clean_guidance_caches() -> None:
    now = time.time()
    for k in list(_query_cache.keys()):
        if now - _query_cache[k][0] > _CACHE_TTL_SECONDS:
            _query_cache.pop(k, None)
    for k in list(_ocr_cache.keys()):
        if now - _ocr_cache[k][0] > _CACHE_TTL_SECONDS:
            _ocr_cache.pop(k, None)


async def read_image_text(
    image_base64: str,
    focus_area: str | None = None,
    prompt_override: str | None = None,
    model: LanguageModel | None = None,
) -> OCRReadTextResponse:
    clean_image = image_base64.strip()
    if not clean_image:
        raise ValueError("image_base64 must not be empty")

    _clean_guidance_caches()
    cache_key = f"{clean_image[-64:]}:{focus_area or ''}:{prompt_override or ''}"
    if cache_key in _ocr_cache:
        cached_time, cached_res = _ocr_cache[cache_key]
        if time.time() - cached_time < _CACHE_TTL_SECONDS:
            return cached_res

    system_prompt = (
        "You are SightGuide OCR, an expert assistive visual reading and document analysis companion for a blind or visually impaired person.\n"
        "Your mission is to describe the item or scene in view and completely read out EVERYTHING written on it in full detail without summarizing away any words.\n\n"
        "Guidelines:\n"
        "1. Visual & Physical Context: First describe what object or scene the text is on (e.g. 'This is a white medicine bottle', 'This is a printed document on a desk', 'This is a street sign', 'This is a computer screen'). Describe its shape, color, and visual layout.\n"
        "2. Complete Verbatim Reading: Read out all text thoroughly and accurately. Do NOT summarize or shorten what is written. Read out titles, headings, body text, instructions, dates, numbers, ingredients, warnings, nutritional information, prices, and fine print from start to finish.\n"
        "3. Clear Structure: Organize your spoken description naturally (top to bottom, main heading first, then detailed sections).\n"
        "4. If no text is visible: Describe what object or scene is currently in the camera frame, and give helpful advice on how to position the camera or improve lighting to capture text.\n"
        "5. Provide your output as a valid JSON object with the following structure:\n"
        "{\n"
        '  "summary": "A comprehensive spoken narrative that first describes the object and setting, and then speaks out everything written on it in full, natural, flowing speech.",\n'
        '  "text": "Full verbatim extracted text found in the image. Preserve exact wording, line breaks, and numbers.",\n'
        '  "reading_type": "product_label" | "sign" | "document" | "handwriting" | "screen" | "general",\n'
        '  "priority": "normal" | "warning" | "urgent"\n'
        "}\n"
        "Output ONLY the JSON object. Do not include markdown code blocks or additional commentary."
    )

    if focus_area:
        system_prompt += f"\nUser focus area: {focus_area}"
    if prompt_override:
        system_prompt += f"\nAdditional Context / User Question: {prompt_override}"

    lm = model or get_default_language_model()
    raw_response = await lm.complete(system_prompt, image_base64=clean_image)

    parsed_summary = raw_response
    parsed_text = raw_response
    parsed_type = "general"
    parsed_priority = "normal"

    try:
        json_match = re.search(r"\{.*\}", raw_response, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(0))
            parsed_summary = str(data.get("summary", raw_response)).strip()
            parsed_text = str(data.get("text", parsed_summary)).strip()
            parsed_type = str(data.get("reading_type", "general"))
            parsed_priority = str(data.get("priority", "normal"))
            if parsed_priority not in {"normal", "warning", "urgent"}:
                parsed_priority = "normal"
    except Exception:
        parsed_summary = raw_response.strip()
        parsed_text = raw_response.strip()

    result = OCRReadTextResponse(
        text=parsed_text,
        summary=parsed_summary,
        reading_type=parsed_type,
        priority=parsed_priority,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    _ocr_cache[cache_key] = (time.time(), result)
    return result


async def detect_obstacles_and_objects(
    image_base64: str,
    mode: str = "navigation",
    prompt_override: str | None = None,
    model: LanguageModel | None = None,
) -> VisionDetectionResponse:
    clean_image = image_base64.strip()
    if not clean_image:
        raise ValueError("image_base64 must not be empty")
    lm = model or get_default_language_model()

    if mode in {"reading", "ocr"}:
        ocr_res = await read_image_text(clean_image, prompt_override=prompt_override, model=lm)
        return VisionDetectionResponse(
            summary=ocr_res.summary,
            obstacles=[],
            priority=ocr_res.priority,
            extracted_text=ocr_res.text,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    # 1. Run local YOLO for fast bounding boxes & obstacle distance tracking
    parsed_obstacles: list[DetectedObstacle] = []
    try:
        frame = _decode_base64_image(clean_image)
        yolo = _load_yolo_model()
        results = yolo.predict(source=frame, verbose=False)
        detections = results[0] if results else None

        if detections is not None and getattr(detections, "boxes", None) is not None:
            names = getattr(yolo, "names", {}) or {}
            image_height, image_width = frame.shape[:2]
            for box in detections.boxes:
                cls_id = int(_scalar(box.cls[0]))
                label = str(names.get(cls_id, f"class_{cls_id}"))
                if label not in _COCO_HAZARD_LABELS and label not in {"backpack", "umbrella", "handbag", "suitcase"}:
                    continue
                xyxy = box.xyxy[0]
                if hasattr(xyxy, "tolist"):
                    xyxy = xyxy.tolist()
                x1, y1, x2, y2 = map(float, xyxy)
                x_center = (x1 + x2) / 2.0
                box_width = max(x2 - x1, 1.0)
                box_height = max(y2 - y1, 1.0)
                clock = _clock_position_from_box(x_center, image_width)
                distance = _distance_text_from_box(box_width, box_height, image_width, image_height)
                hazard_level = "urgent" if label in {"person", "car", "bus", "truck", "motorcycle", "bicycle"} and distance in {"very close", "close"} else "medium"
                if label in {"traffic light", "stop sign"}:
                    hazard_level = "medium"
                parsed_obstacles.append(
                    DetectedObstacle(
                        label=label,
                        location_clock=clock,
                        distance=distance,
                        hazard_level=hazard_level,
                    )
                )
    except Exception as yolo_err:
        logger.warning("YOLO detection skipped: %s", yolo_err)

    # 2. Call Multimodal Vision AI (Gemini / OpenAI) to describe the WHOLE SCENE vividly
    yolo_hint = ""
    if parsed_obstacles:
        obs_desc = ", ".join(f"{obs.label} at {obs.location_clock} ({obs.distance})" for obs in parsed_obstacles)
        yolo_hint = f"\nPhysical items detected in field of view: {obs_desc}."

    system_prompt = (
        "You are SightGuide, an expert assistive vision guide for a blind or visually impaired person.\n"
        "Thoroughly and vividly describe the ENTIRE SCENE in front of the camera in rich, natural spoken detail so the user can visualize their entire surroundings clearly.\n"
        "Do NOT give a brief 1-sentence summary. Describe the whole scene comprehensively.\n\n"
        "Guidelines:\n"
        "1. Overall Setting & Environment: Identify where the user is (e.g. indoor living room, bedroom, kitchen, hallway, office, sidewalk, street, store) and note the lighting and atmosphere.\n"
        "2. Comprehensive Scene Description: Describe all visible objects, furniture, people (their appearance, clothing, actions), walls, doors, windows, and pathways across the whole field of view (left, center, and right; foreground, midground, and background).\n"
        "3. Spatial Positions & Distances: Give clock directions (12 o'clock = directly ahead, 10 o'clock = front-left, 2 o'clock = front-right, 9 o'clock = left, 3 o'clock = right) and estimated distance in meters or steps.\n"
        "4. Walking Path & Hazards: Describe whether the direct walking path ahead is clear and open, or if there are obstacles, stairs, elevation changes, cords, curbs, or doors.\n"
        "5. Visible Text or Signs: Read and describe any visible signs, screens, or brand names.\n"
        f"{yolo_hint}\n"
        "Provide your response as a valid JSON object with the following structure:\n"
        "{\n"
        '  "summary": "A rich, thorough, vivid spoken narrative describing the entire scene, setting, all objects, people, spatial positions, walking path conditions, and visible text in full detail.",\n'
        '  "priority": "urgent" | "warning" | "normal",\n'
        '  "obstacles": [\n'
        '    {\n'
        '      "label": "name of person, vehicle, or obstacle",\n'
        '      "location_clock": "12 o\'clock",\n'
        '      "distance": "approximate distance (e.g. 2 meters, close, far)",\n'
        '      "hazard_level": "low" | "medium" | "urgent"\n'
        '    }\n'
        '  ],\n'
        '  "extracted_text": "any readable text visible in the scene, if any"\n'
        "}\n"
        "Output ONLY the JSON object. Do not include markdown code blocks or additional commentary."
    )

    if prompt_override:
        system_prompt += f"\nAdditional User Context / Question: {prompt_override}"

    try:
        raw_response = await lm.complete(system_prompt, image_base64=clean_image)
        parsed_summary = raw_response
        parsed_priority = "normal"
        llm_obstacles: list[DetectedObstacle] = []
        parsed_text: str | None = None

        json_match = re.search(r"\{.*\}", raw_response, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(0))
            parsed_summary = _clean_spoken_answer(str(data.get("summary", raw_response)))
            parsed_priority = data.get("priority", "normal")
            if parsed_priority not in {"normal", "warning", "urgent"}:
                parsed_priority = "normal"
            parsed_text = data.get("extracted_text")
            for obs in data.get("obstacles", []):
                if isinstance(obs, dict) and "label" in obs:
                    llm_obstacles.append(
                        DetectedObstacle(
                            label=str(obs.get("label", "")),
                            location_clock=str(obs.get("location_clock", "12 o'clock")),
                            distance=str(obs.get("distance", "nearby")),
                            hazard_level=str(obs.get("hazard_level", "low")),
                        )
                    )
            # Combine YOLO obstacles with LLM obstacles (deduplicating by label)
            existing_labels = {o.label.lower() for o in parsed_obstacles}
            for lo in llm_obstacles:
                if lo.label.lower() not in existing_labels:
                    parsed_obstacles.append(lo)
                    existing_labels.add(lo.label.lower())

        return VisionDetectionResponse(
            summary=parsed_summary,
            obstacles=parsed_obstacles,
            priority=parsed_priority,
            extracted_text=parsed_text,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as llm_err:
        logger.warning("LLM complete failed in detect_obstacles_and_objects: %s. Using YOLO fallback.", llm_err)
        parsed_priority = _priority_from_labels(parsed_obstacles)
        if parsed_obstacles:
            summary = f"Detected {len(parsed_obstacles)} object{'s' if len(parsed_obstacles) != 1 else ''}."
            urgent_labels = [obs.label for obs in parsed_obstacles if obs.hazard_level == "urgent"]
            if urgent_labels:
                summary = f"Caution: {', '.join(urgent_labels)} detected nearby."
            elif any(obs.hazard_level == "medium" for obs in parsed_obstacles):
                summary = f"Be careful. {parsed_obstacles[0].label.capitalize()} detected ahead."
        else:
            summary = "No major hazards detected in view."
            parsed_priority = "normal"

        if prompt_override:
            summary = f"{summary} {prompt_override.strip()}"

        return VisionDetectionResponse(
            summary=summary,
            obstacles=parsed_obstacles,
            priority=parsed_priority,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


async def handle_voice_assistant_query(
    question: str,
    image_base64: str | None = None,
    context: str | None = "general",
    context_turns: list[tuple[str, str]] | None = None,
    model: LanguageModel | None = None,
) -> VoiceAssistantQueryResponse:
    clean_question = question.strip()
    if not clean_question:
        raise ValueError("question must not be empty")

    _clean_guidance_caches()
    frame_slice = (image_base64 or "").strip()[-64:]
    cache_key = f"{clean_question.lower()}:{frame_slice}:{context or ''}"
    if cache_key in _query_cache:
        cached_time, cached_res = _query_cache[cache_key]
        if time.time() - cached_time < _CACHE_TTL_SECONDS:
            return cached_res

    lower_q = clean_question.lower()

    # Instant intent matching for app control commands
    if any(p in lower_q for p in ["start auto", "start continuous", "auto scan", "enable continuous", "start scanning"]):
        return VoiceAssistantQueryResponse(
            answer="Continuous auto-scanning is now enabled. I will scan for obstacles every 3 seconds.",
            action="start_scan",
            priority="normal",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    if any(p in lower_q for p in ["stop auto", "stop continuous", "stop scan", "pause scanning", "stop listening"]):
        return VoiceAssistantQueryResponse(
            answer="Continuous scanning stopped. You can tap or ask anytime for guidance.",
            action="stop_scan",
            priority="normal",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    if any(p in lower_q for p in ["flip camera", "switch camera", "front camera", "back camera", "toggle camera"]):
        return VoiceAssistantQueryResponse(
            answer="Switching camera direction.",
            action="switch_camera",
            priority="normal",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    if any(p in lower_q for p in ["mute voice", "turn off voice", "mute audio", "silence", "be quiet"]):
        return VoiceAssistantQueryResponse(
            answer="Voice audio is now muted.",
            action="mute",
            priority="normal",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    # Navigation Voice Intent matching (shared with the live voice pipeline)
    destination_target = extract_navigation_destination(clean_question)
    if destination_target:
        return VoiceAssistantQueryResponse(
            answer=f"Starting walking navigation to {destination_target}. Loading your route and tracking your GPS position.",
            action="start_navigation",
            navigation_destination=destination_target,
            priority="normal",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    # OCR / Reading Voice Intent matching
    is_reading_query = (
        any(
            p in lower_q
            for p in [
                "what is written",
                "what's written",
                "whats written",
                "what does this say",
                "what does it say",
                "what does that say",
                "what does the sign say",
                "what does this sign say",
                "what does the text say",
                "what does this text say",
                "what does the label say",
                "what does this label say",
                "read this",
                "read text",
                "read the text",
                "read sign",
                "read the sign",
                "read label",
                "read the label",
                "read document",
                "read paper",
                "read prescription",
                "read menu",
                "read screen",
                "read book",
                "read notice",
                "transcribe",
            ]
        )
        or bool(re.search(r"\b(?:read\s+(?:the\s+)?(?:label|text|sign|document|menu|book|paper|screen|notice|page|prescription|this)|what\s+does\s+.+\s+say|what\s+is\s+written)\b", lower_q))
        or context in {"reading", "ocr"}
    )
    if is_reading_query and image_base64:
        ocr_res = await read_image_text(
            image_base64=image_base64,
            prompt_override=clean_question,
            model=model,
        )
        return VoiceAssistantQueryResponse(
            answer=ocr_res.summary,
            action="read_text",
            priority=ocr_res.priority,
            extracted_text=ocr_res.text,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    # Specialized Multimodal Prompt for Blind Navigation and Held Object Inspection
    system_prompt = (
        "You are SightGuide, an ultra-intelligent, compassionate voice assistant for a blind or visually impaired person.\n"
        "Answer the user's request directly and naturally as a spoken response.\n"
        "Do not repeat the user's question, do not quote it, and do not begin with 'The user asks'.\n"
        "Infer the intended task from the question and answer the result, not the command text.\n\n"
        "Instructions based on context and question:\n"
        "1. Reading & Text Inspection ('What is written?', 'Read this', 'Read label/sign'):\n"
        "   - First describe what item or document is in view, then read out all written text thoroughly and completely without summarizing away details.\n"
        "2. Held Object / In Hand Inspection ('What is in my hand?', 'What am I holding?', 'What object is this?'):\n"
        "   - Identify the item in their hand or foreground, describe its physical features, color, and read any visible text.\n"
        "3. Room / Indoor Navigation ('Navigate room', 'Where is the chair / door / desk?', 'How to walk in this room?'):\n"
        "   - Give clear walking directions, mention open corridors, doorway positions, and furniture with exact clock directions (12 o'clock = ahead, 10 o'clock = left ahead, 2 o'clock = right ahead) and distance in meters/feet.\n"
        "4. Street / Outdoor Navigation ('Navigate street', 'Can I cross?', 'Where is the sidewalk / curb?'):\n"
        "   - Identify crosswalks, sidewalk borders, curbs, moving vehicles, bikes, and drop-offs. Prioritize safety.\n"
        "5. Surroundings / Scene Description ('What is in my surroundings?', 'What do you see?', 'Describe what is in front of me'):\n"
        "   - Describe the ENTIRE SCENE in rich, thorough detail: the setting, all objects, people, spatial layout, walking path, and visible text. Do not give a brief summary; paint a full spoken picture of the environment.\n\n"
        "Tone & Format:\n"
        "- Speak naturally, vividly, and descriptively so the user understands their full surroundings.\n"
        "- Do not use bullet points or markdown code blocks; answer directly as natural flowing speech.\n"
        "- If an immediate hazard exists, start with 'Caution:' or 'Warning:'."
    )

    # Short-term conversation history lets follow-ups reference earlier answers.
    if context_turns:
        history_lines = [
            f"{'You' if role == 'assistant' else 'User'} said: {turn_text}"
            for role, turn_text in context_turns[-8:]
        ]
        if history_lines:
            system_prompt += "\n\nRecent conversation for context (use it only to understand follow-ups):\n" + "\n".join(history_lines)

    lm = model or get_default_language_model()
    try:
        response_text = await lm.complete(system_prompt, image_base64=image_base64)
    except Exception:
        response_text = _fallback_voice_answer(clean_question)

    priority = "normal"
    lower_res = response_text.lower()
    if any(w in lower_res for w in ["warning:", "caution:", "danger", "approaching vehicle", "stairs down", "drop-off", "collision"]):
        priority = "warning" if ("caution:" in lower_res or "warning:" in lower_res) else "urgent"

    res = VoiceAssistantQueryResponse(
        answer=(
            _fallback_voice_answer(clean_question)
            if _is_echo(response_text, clean_question)
            else (_clean_spoken_answer(response_text, clean_question) or response_text.strip())
        ),
        action="speak",
        priority=priority,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    _query_cache[cache_key] = (time.time(), res)
    return res


async def calculate_walking_route(
    origin_lat: float,
    origin_lng: float,
    destination: str,
    destination_lat: float | None = None,
    destination_lng: float | None = None,
) -> NavigationRouteResponse:
    google_key = settings.google_maps_api_key or os.getenv("GOOGLE_MAPS_API_KEY", "").strip()

    # 1. Google Maps Directions API (Walking Profile) if API key configured
    if _google_available():
        try:
            dest_query = f"{destination_lat},{destination_lng}" if (destination_lat and destination_lng) else destination
            url = "https://maps.googleapis.com/maps/api/directions/json"
            params = {
                "origin": f"{origin_lat},{origin_lng}",
                "destination": dest_query,
                "mode": "walking",
                "key": google_key,
            }
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url, params=params)
                data = resp.json()
                if data.get("status") != "OK" or not data.get("routes"):
                    _mark_google_unusable_if_needed(data)
                else:
                    route = data["routes"][0]
                    leg = route["legs"][0]
                    steps: list[NavigationStep] = []

                    for s in leg.get("steps", []):
                        raw_html = s.get("html_instructions", "")
                        clean_instruction = re.sub(r"<[^>]+>", " ", raw_html)
                        clean_instruction = html.unescape(" ".join(clean_instruction.split()))
                        maneuver = str(s.get("maneuver", "straight"))
                        steps.append(
                            NavigationStep(
                                instruction=clean_instruction,
                                distance_text=s.get("distance", {}).get("text", ""),
                                distance_meters=float(s.get("distance", {}).get("value", 0)),
                                duration_text=s.get("duration", {}).get("text", ""),
                                maneuver=maneuver,
                                start_lat=s.get("start_location", {}).get("lat"),
                                start_lng=s.get("start_location", {}).get("lng"),
                                end_lat=s.get("end_location", {}).get("lat"),
                                end_lng=s.get("end_location", {}).get("lng"),
                            )
                        )

                    return NavigationRouteResponse(
                        destination_name=leg.get("end_address", destination),
                        total_distance=leg.get("distance", {}).get("text", ""),
                        total_duration=leg.get("duration", {}).get("text", ""),
                        summary=route.get("summary", "Walking route via sidewalks"),
                        steps=steps,
                        overview_polyline=route.get("overview_polyline", {}).get("points") or None,
                        provider="google_maps",
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    )
        except Exception:
            pass

    # 2. OpenStreetMap Nominatim + OSRM Foot Profile Fallback
    try:
        dest_lat = destination_lat
        dest_lng = destination_lng
        dest_name = destination

        # Geocode destination if coordinates not directly passed.
        if dest_lat is None or dest_lng is None:
            cached_geo = _geocode_lookup_cached(destination)
            if cached_geo:
                dest_lat, dest_lng, dest_name = cached_geo
            else:
                try:
                    searched = await search_destination_place(origin_lat, origin_lng, destination)
                    dest_lat = searched.lat
                    dest_lng = searched.lng
                    dest_name = searched.name
                    _cache_geocode(destination, dest_lat, dest_lng, dest_name)
                except Exception:
                    pass

        if dest_lat is not None and dest_lng is not None:
            osrm_data = _osrm_route_lookup_cached(origin_lat, origin_lng, dest_lat, dest_lng)
            if osrm_data is None:
                osrm_url = f"https://router.project-osrm.org/route/v1/foot/{origin_lng},{origin_lat};{dest_lng},{dest_lat}?overview=full&steps=true"
                async with httpx.AsyncClient(timeout=6.0) as client:
                    osrm_res = await client.get(osrm_url)
                    osrm_data = osrm_res.json()
                    if osrm_data.get("code") == "Ok" and osrm_data.get("routes"):
                        _cache_osrm_route(origin_lat, origin_lng, dest_lat, dest_lng, osrm_data)
                if osrm_data.get("code") != "Ok" or not osrm_data.get("routes"):
                    osrm_data = None
            if osrm_data and osrm_data.get("routes"):
                r = osrm_data["routes"][0]
                legs = r["legs"][0]
                steps: list[NavigationStep] = []

                for st in legs.get("steps", []):
                    m = st.get("maneuver", {})
                    m_type = m.get("type", "continue")
                    modifier = m.get("modifier", "")
                    maneuver_str = f"{m_type}-{modifier}".strip("-") if modifier else m_type
                    name = st.get("name") or "the sidewalk"
                    dist_m = float(st.get("distance", 0))
                    dur_s = float(st.get("duration", 0))

                    # OSRM maneuver locations are [lng, lat]
                    loc = m.get("location")
                    start_lat = float(loc[1]) if isinstance(loc, list) and len(loc) == 2 else None
                    start_lng = float(loc[0]) if isinstance(loc, list) and len(loc) == 2 else None

                    if m_type == "arrive":
                        inst = f"You have arrived at {dest_name}"
                    elif modifier:
                        inst = f"Turn {modifier} onto {name}"
                    else:
                        inst = f"Head along {name}"

                    steps.append(
                        NavigationStep(
                            instruction=inst,
                            distance_text=f"{int(dist_m)} m" if dist_m < 1000 else f"{round(dist_m/1000, 1)} km",
                            distance_meters=dist_m,
                            duration_text=f"{max(1, int(dur_s // 60))} min",
                            maneuver=maneuver_str,
                            start_lat=start_lat,
                            start_lng=start_lng,
                        )
                    )

                tot_dist = r.get("distance", 0)
                tot_dur = r.get("duration", 0)

                return NavigationRouteResponse(
                    destination_name=dest_name,
                    total_distance=f"{int(tot_dist)} m" if tot_dist < 1000 else f"{round(tot_dist/1000, 1)} km",
                    total_duration=f"{max(1, int(tot_dur // 60))} mins",
                    summary="Walking route via pedestrian sidewalks",
                    steps=steps,
                    overview_polyline=r.get("geometry") or None,
                    provider="openstreetmap_osrm",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
    except Exception:
        pass

    # 3. Reliable Fallback Walking Steps
    return NavigationRouteResponse(
        destination_name=destination,
        total_distance="250 m",
        total_duration="3 mins",
        summary="Walking path",
        steps=[
            NavigationStep(
                instruction=f"Walk straight on the sidewalk towards {destination}",
                distance_text="100 m",
                distance_meters=100.0,
                duration_text="1 min",
                maneuver="straight",
            ),
            NavigationStep(
                instruction="Turn right at the crosswalk and continue straight",
                distance_text="150 m",
                distance_meters=150.0,
                duration_text="2 mins",
                maneuver="turn-right",
            ),
            NavigationStep(
                instruction=f"You have arrived at {destination}",
                distance_text="0 m",
                distance_meters=0.0,
                duration_text="0 min",
                maneuver="arrive",
            ),
        ],
        provider="simulated",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


AMENITY_SYNONYMS: dict[str, str] = {
    "hospital": "hospital",
    "hospitals": "hospital",
    "emergency room": "hospital",
    "er": "hospital",
    "urgent care": "clinic",
    "clinic": "clinic",
    "clinics": "clinic",
    "doctor": "doctors",
    "doctors": "doctors",
    "medical center": "hospital",
    "pharmacy": "pharmacy",
    "pharmacies": "pharmacy",
    "chemist": "pharmacy",
    "drugstore": "pharmacy",
    "police": "police",
    "police station": "police",
    "fire station": "fire_station",
    "bank": "bank",
    "banks": "bank",
    "atm": "atm",
    "atms": "atm",
    "cash machine": "atm",
    "restaurant": "restaurant",
    "restaurants": "restaurant",
    "food": "restaurant",
    "cafe": "cafe",
    "coffee": "cafe",
    "coffee shop": "cafe",
    "supermarket": "supermarket",
    "supermarkets": "supermarket",
    "grocery": "supermarket",
    "grocery store": "supermarket",
    "convenience store": "convenience",
    "park": "park",
    "gas station": "fuel",
    "petrol pump": "fuel",
    "petrol station": "fuel",
    "hotel": "hotel",
    "library": "library",
    "post office": "post_office",
    "bus stop": "bus_station",
    "bus station": "bus_station",
    "subway station": "station",
    "metro station": "station",
    "train station": "station",
    "school": "school",
    "university": "university",
}

_STRIP_PREFIXES = re.compile(
    r"^(?:(?:navigate|take\s+me|walk|go|head|guide\s+me|route|directions)\s+(?:to|towards)\s+|"
    r"(?:set|change)\s+(?:the\s+)?destination\s+(?:to|as)\s+|"
    r"destination\s+(?:to|is)\s+|"
    r"(?:find|search\s+for|where\s+is|look\s+for)\s+(?:the\s+|a\s+|an\s+)?|"
    r"how\s+(?:do\s+i|can\s+i|to)\s+(?:get|walk|go|reach)\s+(?:to\s+)?|"
    r"(?:the\s+)?(?:nearest|closest)\s+|"
    r"(?:a|an|the)\s+)+",
    re.IGNORECASE,
)

_STRIP_SUFFIXES = re.compile(
    r"(?:\s+(?:near\s+me|nearby|around\s+here|close\s+to\s+me|closest\s+to\s+me|around\s+me))+\s*$",
    re.IGNORECASE,
)


def clean_place_search_query(text: str) -> tuple[str, str | None, bool]:
    """Extract cleaned search term, optional OSM amenity tag, and is_nearby flag.

    E.g.:
    "the nearest hospital" -> ("hospital", "hospital", True)
    "navigate to the nearest pharmacy" -> ("pharmacy", "pharmacy", True)
    "where is the nearest clinic" -> ("clinic", "clinic", True)
    "Starbucks" -> ("Starbucks", None, False)
    "123 Main Street" -> ("123 Main Street", None, False)
    """
    trimmed = text.strip().strip("?.!, \t")
    lower = trimmed.lower()
    is_nearby = bool(
        re.search(r"\b(nearest|closest|near\s+me|nearby|around\s+here)\b", lower)
    )
    cleaned = _STRIP_PREFIXES.sub("", trimmed)
    cleaned = _STRIP_SUFFIXES.sub("", cleaned).strip().strip("?.!, \t")
    if not cleaned:
        cleaned = trimmed

    amenity = AMENITY_SYNONYMS.get(cleaned.lower())
    if amenity is not None:
        is_nearby = True
    return cleaned, amenity, is_nearby


async def search_destination_place(
    origin_lat: float,
    origin_lng: float,
    query: str,
) -> PlaceSearchResult:
    clean_query = query.strip()
    if not clean_query:
        raise ValueError("query must not be empty")

    cleaned_name, amenity_tag, is_nearby = clean_place_search_query(clean_query)
    google_key = settings.google_maps_api_key or os.getenv("GOOGLE_MAPS_API_KEY", "").strip()

    # 1. Google Places Search (Nearby Search or Text Search)
    if _google_available():
        # A) Nearby search if finding nearest place or recognized amenity
        if is_nearby or amenity_tag:
            try:
                url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
                params = {
                    "location": f"{origin_lat},{origin_lng}",
                    "radius": 5000,
                    "keyword": cleaned_name,
                    "key": google_key,
                }
                if amenity_tag:
                    params["type"] = amenity_tag
                async with httpx.AsyncClient(timeout=6.0) as client:
                    resp = await client.get(url, params=params)
                    data = resp.json()
                if data.get("status") not in {"OK", "ZERO_RESULTS"}:
                    _mark_google_unusable_if_needed(data)
                elif data.get("results"):
                    candidates = []
                    for r in data["results"]:
                        c_lat = float(r["geometry"]["location"]["lat"])
                        c_lng = float(r["geometry"]["location"]["lng"])
                        dist_m = _haversine_meters(origin_lat, origin_lng, c_lat, c_lng)
                        candidates.append((dist_m, r, c_lat, c_lng))
                    if candidates:
                        candidates.sort(key=lambda x: x[0])
                        dist_m, res, dest_lat, dest_lng = candidates[0]
                        name = res.get("name") or cleaned_name
                        formatted_addr = res.get("vicinity") or res.get("formatted_address") or name
                        dist_text = f"{int(dist_m)} meters" if dist_m < 1000 else f"{round(dist_m / 1000, 1)} km"
                        duration_text = f"{max(1, int(round(dist_m / 78)))} mins walk"
                        return PlaceSearchResult(
                            name=name,
                            formatted_address=formatted_addr,
                            lat=dest_lat,
                            lng=dest_lng,
                            distance_text=dist_text,
                            distance_meters=dist_m,
                            estimated_duration=duration_text,
                            provider="google_places",
                            timestamp=datetime.now(timezone.utc).isoformat(),
                        )
            except Exception:
                pass

        # B) Text Search
        try:
            url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
            search_text = f"{cleaned_name} near me" if is_nearby else clean_query
            params = {
                "query": search_text,
                "location": f"{origin_lat},{origin_lng}",
                "radius": 5000,
                "key": google_key,
            }
            async with httpx.AsyncClient(timeout=6.0) as client:
                resp = await client.get(url, params=params)
                data = resp.json()
            if data.get("status") not in {"OK", "ZERO_RESULTS"}:
                _mark_google_unusable_if_needed(data)
            elif data.get("results"):
                candidates = []
                for r in data["results"]:
                    c_lat = float(r["geometry"]["location"]["lat"])
                    c_lng = float(r["geometry"]["location"]["lng"])
                    dist_m = _haversine_meters(origin_lat, origin_lng, c_lat, c_lng)
                    candidates.append((dist_m, r, c_lat, c_lng))
                if candidates:
                    candidates.sort(key=lambda x: x[0])
                    dist_m, res, dest_lat, dest_lng = candidates[0]
                    name = res.get("name") or cleaned_name
                    formatted_addr = res.get("formatted_address") or res.get("vicinity") or name
                    dist_text = f"{int(dist_m)} meters" if dist_m < 1000 else f"{round(dist_m / 1000, 1)} km"
                    duration_text = f"{max(1, int(round(dist_m / 78)))} mins walk"

                    return PlaceSearchResult(
                        name=name,
                        formatted_address=formatted_addr,
                        lat=dest_lat,
                        lng=dest_lng,
                        distance_text=dist_text,
                        distance_meters=dist_m,
                        estimated_duration=duration_text,
                        provider="google_places",
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    )
        except Exception:
            pass

        # C) Google Geocoding API for exact addresses
        try:
            url = "https://maps.googleapis.com/maps/api/geocode/json"
            params = {
                "address": clean_query,
                "key": google_key,
            }
            async with httpx.AsyncClient(timeout=6.0) as client:
                resp = await client.get(url, params=params)
                data = resp.json()
            if data.get("status") not in {"OK", "ZERO_RESULTS"}:
                _mark_google_unusable_if_needed(data)
            elif data.get("results"):
                res = data["results"][0]
                dest_lat = float(res["geometry"]["location"]["lat"])
                dest_lng = float(res["geometry"]["location"]["lng"])
                formatted_addr = res.get("formatted_address", clean_query)
                name = formatted_addr.split(",")[0]

                dist_m = _haversine_meters(origin_lat, origin_lng, dest_lat, dest_lng)
                dist_text = f"{int(dist_m)} meters" if dist_m < 1000 else f"{round(dist_m / 1000, 1)} km"
                duration_text = f"{max(1, int(round(dist_m / 78)))} mins walk"

                return PlaceSearchResult(
                    name=name,
                    formatted_address=formatted_addr,
                    lat=dest_lat,
                    lng=dest_lng,
                    distance_text=dist_text,
                    distance_meters=dist_m,
                    estimated_duration=duration_text,
                    provider="google_places",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
        except Exception:
            pass

    # 2. OpenStreetMap Nominatim Geocoding fallback
    # Check cache first for exact query string
    cached_geo = _geocode_lookup_cached(clean_query) or _geocode_lookup_cached(cleaned_name)
    if cached_geo and not is_nearby:
        dest_lat, dest_lng, name = cached_geo
        dist_m = _haversine_meters(origin_lat, origin_lng, dest_lat, dest_lng)
        dist_text = f"{int(dist_m)} meters" if dist_m < 1000 else f"{round(dist_m / 1000, 1)} km"
        duration_text = f"{max(1, int(round(dist_m / 78)))} mins walk"
        return PlaceSearchResult(
            name=name,
            formatted_address=name,
            lat=dest_lat,
            lng=dest_lng,
            distance_text=dist_text,
            distance_meters=dist_m,
            estimated_duration=duration_text,
            provider="openstreetmap_nominatim",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    osm_candidates: list[dict] = []
    headers = {"User-Agent": "SightGuideAccessibility/1.0"}

    # For nearby / amenity searches, search within expanding viewbox
    deltas = [0.08, 0.20] if is_nearby else [0.20]
    async with httpx.AsyncClient(timeout=6.0, headers=headers) as client:
        for delta in deltas:
            viewbox = f"{origin_lng-delta},{origin_lat+delta},{origin_lng+delta},{origin_lat-delta}"
            urls: list[str] = []
            if amenity_tag:
                urls.append(
                    f"https://nominatim.openstreetmap.org/search?amenity={amenity_tag}&viewbox={viewbox}&bounded=1&format=json&addressdetails=1&limit=10"
                )
            urls.append(
                f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(cleaned_name)}&viewbox={viewbox}&bounded=1&format=json&addressdetails=1&limit=10"
            )
            for url in urls:
                try:
                    res = await client.get(url)
                    data = res.json()
                    if isinstance(data, list) and data:
                        for item in data:
                            lat = float(item["lat"])
                            lng = float(item["lon"])
                            dist = _haversine_meters(origin_lat, origin_lng, lat, lng)
                            raw_name = item.get("name") or item.get("display_name", "").split(",")[0]
                            display_name = item.get("display_name", raw_name)
                            osm_candidates.append({
                                "name": raw_name,
                                "formatted_address": display_name,
                                "lat": lat,
                                "lng": lng,
                                "dist_m": dist,
                            })
                except Exception:
                    pass
            if osm_candidates:
                break

        # If no viewbox result, try standard unconstrained search
        if not osm_candidates:
            try:
                unbounded_url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(cleaned_name)}&format=json&addressdetails=1&limit=5&lat={origin_lat}&lon={origin_lng}"
                res = await client.get(unbounded_url)
                data = res.json()
                if isinstance(data, list) and data:
                    for item in data:
                        lat = float(item["lat"])
                        lng = float(item["lon"])
                        dist = _haversine_meters(origin_lat, origin_lng, lat, lng)
                        raw_name = item.get("name") or item.get("display_name", "").split(",")[0]
                        display_name = item.get("display_name", raw_name)
                        osm_candidates.append({
                            "name": raw_name,
                            "formatted_address": display_name,
                            "lat": lat,
                            "lng": lng,
                            "dist_m": dist,
                        })
            except Exception:
                pass

    if osm_candidates:
        osm_candidates.sort(key=lambda x: x["dist_m"])
        best = osm_candidates[0]
        dest_lat = best["lat"]
        dest_lng = best["lng"]
        name = best["name"]
        display_name = best["formatted_address"]
        dist_m = best["dist_m"]
        _cache_geocode(clean_query, dest_lat, dest_lng, name)

        dist_text = f"{int(dist_m)} meters" if dist_m < 1000 else f"{round(dist_m / 1000, 1)} km"
        duration_text = f"{max(1, int(round(dist_m / 78)))} mins walk"

        return PlaceSearchResult(
            name=name,
            formatted_address=display_name,
            lat=dest_lat,
            lng=dest_lng,
            distance_text=dist_text,
            distance_meters=dist_m,
            estimated_duration=duration_text,
            provider="openstreetmap_nominatim",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    # 3. Default fallback result if all external services fail / return empty
    fallback_name = f"Nearest {cleaned_name.title()}" if is_nearby else clean_query
    return PlaceSearchResult(
        name=fallback_name,
        formatted_address=f"{fallback_name}, Local Area",
        lat=origin_lat + 0.002,
        lng=origin_lng + 0.002,
        distance_text="250 meters",
        distance_meters=250.0,
        estimated_duration="3 mins walk",
        provider="openstreetmap_nominatim",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
