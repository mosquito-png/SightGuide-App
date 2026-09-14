"""Voice command orchestration for the SightGuide assistant.

This module turns a spoken transcript into a structured, spoken answer plus
optional device directives. It owns intent resolution and decides *what* to
answer and *which* device action (if any) to request; the browser executes the
device-side mechanics (tel:, sms:, notifications, GPS).

Every intent except general conversation is answered without the LLM, using
device clocks, a real weather API, or the existing YOLO vision pipeline.
"""

import re
import urllib.parse
from datetime import datetime

from app.assistant import intents
from app.schemas.guidance import DetectedObstacle, VoiceAssistantQueryResponse
from app.schemas.voice import DeviceDirective, VoiceCommandResponse
from app.services import guidance as guidance_service
from app.services import weather as weather_service
from app.ai.providers import LanguageModel

_TIME_PATTERN = re.compile(
    r"\b(?:in|for)\s+(\d+)\s*(second|seconds|minute|minutes|min|mins|hour|hours|hr|hrs)\b",
    re.IGNORECASE,
)
_CLOCK_PATTERN = re.compile(
    r"\b(?:at|for)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
    re.IGNORECASE,
)


def _ordinal(day: int) -> str:
    if 10 <= day % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def _current_time_answer() -> str:
    now = datetime.now().astimezone()
    hour = now.strftime("%I").lstrip("0")
    return f"It is {hour}:{now.strftime('%M')} {now.strftime('%p')}."


def _current_date_answer() -> str:
    now = datetime.now().astimezone()
    return f"Today is {now.strftime('%A')}, {now.strftime('%B')} {_ordinal(now.day)}, {now.year}."


def _digits(text: str) -> str:
    return re.sub(r"[^\d+(),. -]", "", text).strip()


def _resolve_call(text: str) -> tuple[str, DeviceDirective | None]:
    target = intents.extract_call_target(text) or ""
    if not target:
        return "Who would you like me to call?", None
    digits = _digits(target)
    is_number = len(digits) >= 3 and target.replace(" ", "").replace("-", "").replace("(", "").replace(")", "").isdigit()
    if is_number:
        return f"Calling {digits} now.", DeviceDirective(action="call", value=digits)
    return (
        f"I will call {target}.",
        DeviceDirective(action="call", value=target),
    )


def _resolve_message(text: str) -> tuple[str, DeviceDirective | None]:
    recipient, body = intents.extract_message_target_and_body(text)
    if not recipient:
        return "Who should I send the message to?", None
    digits = _digits(recipient)
    is_number = bool(digits) and recipient.replace(" ", "").replace("-", "").replace("(", "").replace(")", "").isdigit()
    target_val = digits if is_number and digits else recipient
    params: dict[str, object] = {"recipient": target_val}
    if body:
        params["body"] = body
        return (
            f"Opening a message to {recipient} with text: {body}.",
            DeviceDirective(action="message", value=target_val, parameters=params),
        )
    return (
        f"Opening a message to {recipient}.",
        DeviceDirective(action="message", value=target_val, parameters=params),
    )


def _resolve_search(text: str) -> tuple[str, DeviceDirective]:
    query = intents.extract_search_query(text) or "SightGuide"
    url = f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}"
    message = f"Searching online for {query}."
    directive = DeviceDirective(action="search_web", value=query, parameters={"query": query, "url": url})
    return message, directive


_INTERNAL_SCREENS = {
    "camera": "vision",
    "vision": "vision",
    "ocr": "vision",
    "navigation": "navigation",
    "maps": "navigation",
    "map": "navigation",
    "emergency": "emergency",
    "sos": "emergency",
    "settings": "settings",
    "history": "history",
    "home": "home",
}

_EXTERNAL_APPS = {
    "whatsapp": {"url": "https://wa.me/", "native": "whatsapp://", "name": "WhatsApp"},
    "youtube": {"url": "https://www.youtube.com", "native": "vnd.youtube://", "name": "YouTube"},
    "spotify": {"url": "https://open.spotify.com", "native": "spotify://", "name": "Spotify"},
    "google": {"url": "https://www.google.com", "native": "https://www.google.com", "name": "Google"},
    "browser": {"url": "https://www.google.com", "native": "https://www.google.com", "name": "Browser"},
    "chrome": {"url": "https://www.google.com", "native": "googlechrome://", "name": "Chrome"},
    "gmail": {"url": "https://mail.google.com", "native": "googlegmail://", "name": "Gmail"},
    "email": {"url": "mailto:", "native": "mailto:", "name": "Email"},
    "mail": {"url": "mailto:", "native": "mailto:", "name": "Mail"},
    "maps": {"url": "https://maps.google.com", "native": "geo:0,0", "name": "Google Maps"},
    "google maps": {"url": "https://maps.google.com", "native": "geo:0,0", "name": "Google Maps"},
    "uber": {"url": "https://m.uber.com", "native": "uber://", "name": "Uber"},
}


def _resolve_open_app(text: str) -> tuple[str, DeviceDirective]:
    raw_target = (intents.extract_open_app_target(text) or "").strip().lower()
    # 1. Check internal app screens
    for key, screen_id in _INTERNAL_SCREENS.items():
        if key == raw_target or key in raw_target.split():
            screen_name = "Camera and Vision" if screen_id == "vision" else key.capitalize()
            return (
                f"Opening {screen_name}.",
                DeviceDirective(action="open_screen", value=screen_id, parameters={"screen": screen_id}),
            )

    # 2. Check external apps
    for key, app_info in _EXTERNAL_APPS.items():
        if key in raw_target:
            return (
                f"Opening {app_info['name']} now.",
                DeviceDirective(
                    action="open_external",
                    value=app_info["name"],
                    parameters={"url": app_info["url"], "native": app_info["native"], "name": app_info["name"]},
                ),
            )

    # 3. Fallback search / web open
    app_name = raw_target.capitalize() or "App"
    search_url = f"https://www.google.com/search?q={urllib.parse.quote_plus(raw_target or 'apps')}"
    return (
        f"Searching for {app_name} online.",
        DeviceDirective(
            action="open_external",
            value=app_name,
            parameters={"url": search_url, "name": app_name},
        ),
    )


_REMINDER_SUFFIX_STRIP = re.compile(r"\s+(?:in\s+(?:about\s+)?\d+\s+(?:seconds?|minutes?|mins?|hours?|hrs?))|(?:\bat\s+\d{1,2}(?::\d{2})?\s*(?:am|pm))\s*$", re.IGNORECASE)


def _reminder_seconds(text: str) -> float:
    match = _TIME_PATTERN.search(text)
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        multiplier = {"second": 1, "seconds": 1, "minute": 60, "minutes": 60, "min": 60, "mins": 60,
                       "hour": 3600, "hours": 3600, "hr": 3600, "hrs": 3600}.get(unit, 60)
        return amount * multiplier
    clock = _CLOCK_PATTERN.search(text)
    if clock:
        hour = int(clock.group(1))
        minute = int(clock.group(2) or 0)
        meridiem = (clock.group(3) or "").lower()
        now = datetime.now().astimezone()
        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target = target.replace(day=target.day + 1)
        return max((target - now).total_seconds(), 1.0)
    return 0.0


def _resolve_reminder(text: str) -> tuple[str, DeviceDirective]:
    reminder = (intents.extract_reminder_text(text) or "a reminder").strip()
    reminder = _REMINDER_SUFFIX_STRIP.sub("", reminder).strip()
    if reminder.startswith("to "):
        reminder = reminder[3:].strip()
    seconds = _reminder_seconds(text)
    if seconds > 0:
        parameters: dict[str, object] = {
            "seconds": seconds,
            "text": reminder,
        }
        return (
            f"Reminder set: {reminder}.",
            DeviceDirective(action="reminder", value=reminder, parameters=parameters),
        )
    return (
        f"I will remind you to {reminder}. Please try including a time, like: remind me in 10 minutes.",
        DeviceDirective(action="reminder", value=reminder),
    )


def _resolve_sos(text: str, location_label: str | None) -> tuple[str, DeviceDirective]:
    digits = _digits(text)
    number = digits if re.match(r"^1?\d{10}$", digits) else ""
    message = (
        "Emergency assistance requested. Stay where you are if safe, and "
        "I am directly placing an emergency call to 9341240360 and sending your live GPS location via SMS."
    )
    return message, DeviceDirective(action="sos", value=number or "9341240360", parameters={"location": location_label or ""})


def _resolve_app_control(text: str) -> VoiceCommandResponse:
    lower = text.lower()
    if re.search(r"\b(flip|switch|toggle)\s+(?:the\s+)?camera\b|front\s+camera|back\s+camera", lower):
        return VoiceCommandResponse(
            intent=intents.Intent.APP_CONTROL,
            text="Switching camera direction.",
            priority="normal",
            action="speak",
            directives=[DeviceDirective(action="switch_camera")],
        )
    if re.search(r"\b(scan|scanning)\b", lower):
        started = any(word in lower for word in ("start", "begin", "enable", "turn on", "continuous", "auto"))
        if started:
            return VoiceCommandResponse(
                intent=intents.Intent.APP_CONTROL,
                text="Continuous obstacle scanning started. I will check ahead for hazards.",
                priority="normal",
                action="speak",
                directives=[DeviceDirective(action="start_scan")],
            )
        return VoiceCommandResponse(
            intent=intents.Intent.APP_CONTROL,
            text="Obstacle scanning is already monitoring your view.",
            priority="normal",
            action="speak",
            directives=[DeviceDirective(action="start_scan")],
        )
    if re.search(r"\b(unmute|volume\s+up|louder|speak\s+up)\b", lower):
        return VoiceCommandResponse(
            intent=intents.Intent.APP_CONTROL,
            text="Voice announcements are back on.",
            priority="normal",
            action="speak",
            directives=[DeviceDirective(action="unmute")],
        )
    return VoiceCommandResponse(
        intent=intents.Intent.APP_CONTROL,
        text="Voice announcements muted. Say: hey SightGuide, unmute, to resume.",
        priority="normal",
        action="speak",
        directives=[DeviceDirective(action="mute")],
    )


def _resolve_phone_control(text: str) -> tuple[str, DeviceDirective]:
    """Resolve phone accessibility action and generate device directive."""
    info = intents.extract_phone_control_info(text)
    sub = str(info.get("sub_action", "unknown"))

    if sub == "type":
        content = str(info.get("text", ""))
        return f"Typing: {content}", DeviceDirective(
            action="phone_control",
            value="type",
            parameters={"sub_action": "type", "text": content},
        )

    if sub == "click":
        target = str(info.get("target", "item"))
        ordinal = info.get("ordinal")
        if ordinal is not None and isinstance(ordinal, int) and ordinal > 0:
            ord_names = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth"}
            name = ord_names.get(ordinal, f"number {ordinal}")
            msg = f"Opening the {name} {target}."
        elif ordinal == -1:
            msg = f"Opening the last {target}."
        else:
            msg = f"Clicking {target}."
        params: dict[str, object] = {"sub_action": "click", "target": target}
        if ordinal is not None:
            params["ordinal"] = ordinal
        return msg, DeviceDirective(action="phone_control", value="click", parameters=params)

    if sub == "media":
        cmd = str(info.get("command", "play"))
        msg = "Pausing playback." if cmd == "pause" else ("Resuming playback." if cmd == "resume" else "Playing.")
        return msg, DeviceDirective(
            action="phone_control",
            value="media",
            parameters={"sub_action": "media", "command": cmd},
        )

    if sub == "search":
        query = str(info.get("query", ""))
        return f"Searching for {query}.", DeviceDirective(
            action="phone_control",
            value="search",
            parameters={"sub_action": "search", "query": query, "target": query},
        )

    if sub == "scroll":
        direction = str(info.get("direction", "down"))
        msg = f"Scrolling {direction}."
        return msg, DeviceDirective(
            action="phone_control",
            value="scroll",
            parameters={"sub_action": "scroll", "direction": direction},
        )

    if sub == "global_nav":
        action = str(info.get("global_action", "back"))
        labels = {
            "back": "Going back.",
            "home": "Returning to home screen.",
            "recents": "Showing recent apps.",
            "notifications": "Opening notifications.",
            "quick_settings": "Opening quick settings.",
        }
        msg = labels.get(action, f"Executing {action}.")
        return msg, DeviceDirective(
            action="phone_control",
            value="global_nav",
            parameters={"sub_action": "global_nav", "global_action": action},
        )

    if sub == "read_screen":
        return "Reading the current screen.", DeviceDirective(
            action="phone_control",
            value="read_screen",
            parameters={"sub_action": "read_screen"},
        )

    return f"Performing phone action: {text}", DeviceDirective(
        action="phone_control",
        value="custom",
        parameters={"sub_action": "custom", "text": text},
    )


async def _resolve_navigation(
    text: str, lat: float | None = None, lon: float | None = None
) -> VoiceCommandResponse | None:
    destination = guidance_service.extract_navigation_destination(text)
    if not destination:
        return None

    dest_name = destination
    directives: list[DeviceDirective] = []
    text_answer = f"Starting walking navigation to {dest_name}. Loading your route and tracking your GPS position."

    if lat is not None and lon is not None:
        try:
            place = await guidance_service.search_destination_place(lat, lon, destination)
            dest_name = place.name
            text_answer = f"Starting walking navigation to {dest_name}. {place.distance_text}, about {place.estimated_duration}. Loading your route and tracking your GPS position."
            directives.append(
                DeviceDirective(
                    action="start_navigation",
                    value=dest_name,
                    parameters={"lat": place.lat, "lng": place.lng, "address": place.formatted_address},
                )
            )
        except Exception:
            directives.append(DeviceDirective(action="start_navigation", value=dest_name))
    else:
        directives.append(DeviceDirective(action="start_navigation", value=dest_name))

    return VoiceCommandResponse(
        intent=intents.Intent.NAVIGATION,
        text=text_answer,
        priority="normal",
        action="start_navigation",
        navigation_destination=dest_name,
        directives=directives,
    )


async def _resolve_vision(
    intent: str,
    text: str,
    image_base64: str,
    model: LanguageModel | None,
) -> VoiceCommandResponse:
    if intent in {intents.Intent.OBSTACLE, intents.Intent.DISTANCE}:
        detection = await _detect_obstacles(image_base64)
        if intent == intents.Intent.DISTANCE:
            return _distance_answer(detection)
        detected = [obs.label for obs in detection.obstacles]
        return VoiceCommandResponse(
            intent=intent,
            text=detection.summary,
            priority=detection.priority,
            action="speak",
            detected_items=detected,
        )

    # scene -> rich multimodal description (this genuinely needs the LLM)
    answer = await guidance_service.handle_voice_assistant_query(
        text,
        image_base64=image_base64,
        context="surroundings",
        model=model,
    )
    return VoiceCommandResponse(
        intent=intent,
        text=answer.answer,
        priority=answer.priority,
        action=getattr(answer, "action", "speak"),
        detected_items=getattr(answer, "detected_items", []) or [],
        extracted_text=getattr(answer, "extracted_text", None),
    )


async def _detect_obstacles(image_base64: str):
    return await guidance_service.detect_obstacles_and_objects(image_base64, mode="navigation")


def _obstacle_distance_gauge(obs: DetectedObstacle) -> int:
    order = {"very close": 4, "close": 3, "a few meters away": 2, "nearby": 2, "far": 1}
    return order.get(obs.distance.lower(), 0)


def _distance_answer(detection) -> VoiceCommandResponse:
    if not detection.obstacles or not any(detection.obstacles):
        return VoiceCommandResponse(
            intent=intents.Intent.DISTANCE,
            text="I do not see any objects close enough to measure a distance to.",
            priority="normal",
            action="speak",
            detected_items=[],
        )
    nearest = max(detection.obstacles, key=_obstacle_distance_gauge)
    other = [obs.label for obs in detection.obstacles]
    return VoiceCommandResponse(
        intent=intents.Intent.DISTANCE,
        text=f"The nearest object is a {nearest.label}, {nearest.distance}, at {nearest.location_clock}.",
        priority=detection.priority,
        action="speak",
        detected_items=other,
    )


async def _resolve_weather(
    text: str,
    lat: float | None,
    lon: float | None,
    location_label: str | None,
) -> VoiceCommandResponse:
    if lat is None or lon is None:
        lat, lon, label = weather_service.resolve_location_defaults()
        location_label = location_label or label
    data = await weather_service.fetch_weather(lat, lon)
    report = weather_service.parse_weather_report(data)
    rain_question = weather_service.is_rain_question(text)
    if rain_question:
        answer = weather_service.format_rain_answer(report, location_label)
    else:
        answer = weather_service.format_weather_answer(report, location_label)
    return VoiceCommandResponse(
        intent=intents.Intent.WEATHER,
        text=answer,
        priority="normal",
        action="speak",
    )


async def _resolve_general(
    text: str,
    context_turns: list[tuple[str, str]],
    image_base64: str | None,
    model: LanguageModel | None,
) -> VoiceCommandResponse:
    answer = await guidance_service.handle_voice_assistant_query(
        text,
        image_base64=image_base64,
        context="general",
        context_turns=context_turns,
        model=model,
    )
    return VoiceCommandResponse(
        intent=intents.Intent.GENERAL,
        text=answer.answer,
        priority=answer.priority,
        action="speak",
        detected_items=getattr(answer, "detected_items", []) or [],
        extracted_text=getattr(answer, "extracted_text", None),
    )


async def handle_voice_command(
    text: str,
    context: list[tuple[str, str]] | None = None,
    lat: float | None = None,
    lon: float | None = None,
    location_label: str | None = None,
    image_base64: str | None = None,
    model: LanguageModel | None = None,
) -> VoiceCommandResponse:
    """Route a spoken command and produce the assistant's spoken reply."""
    clean = " ".join((text or "").strip().split())
    turns = list(context or [])
    intent = intents.classify_intent(clean, turns)

    if intent == intents.Intent.SOS:
        message, directive = _resolve_sos(clean, location_label)
        return VoiceCommandResponse(intent=intent, text=message, priority="urgent", directives=[directive])

    if intent == intents.Intent.CANCEL:
        return VoiceCommandResponse(
            intent=intent,
            text="Stopped. I am back to listening for the wake word.",
            priority="normal",
            action="stop_all",
        )

    if intent == intents.Intent.TIME:
        return VoiceCommandResponse(intent=intent, text=_current_time_answer(), priority="normal")

    if intent == intents.Intent.DATE:
        return VoiceCommandResponse(intent=intent, text=_current_date_answer(), priority="normal")

    if intent == intents.Intent.WEATHER:
        try:
            return await _resolve_weather(clean, lat, lon, location_label)
        except Exception as error:
            return VoiceCommandResponse(
                intent=intent,
                text=(
                    "I could not reach the weather service right now. "
                    "Please make sure you have an internet connection and try again."
                ),
                priority="normal",
            )

    if intent == intents.Intent.NAVIGATION:
        navigation = await _resolve_navigation(clean, lat=lat, lon=lon)
        if navigation is not None:
            return navigation

    if intent == intents.Intent.CALL:
        message, directive = _resolve_call(clean)
        return VoiceCommandResponse(
            intent=intent,
            text=message,
            priority="normal",
            directives=[directive] if directive else [],
        )

    if intent == intents.Intent.MESSAGE:
        message, directive = _resolve_message(clean)
        return VoiceCommandResponse(
            intent=intent,
            text=message,
            priority="normal",
            directives=[directive] if directive else [],
        )

    if intent == intents.Intent.REMINDER:
        message, directive = _resolve_reminder(clean)
        return VoiceCommandResponse(
            intent=intent,
            text=message,
            priority="normal",
            directives=[directive],
        )

    if intent == intents.Intent.SEARCH:
        message, directive = _resolve_search(clean)
        return VoiceCommandResponse(
            intent=intent,
            text=message,
            priority="normal",
            directives=[directive],
        )

    if intent == intents.Intent.OPEN_APP:
        message, directive = _resolve_open_app(clean)
        return VoiceCommandResponse(
            intent=intent,
            text=message,
            priority="normal",
            directives=[directive],
        )

    if intent == intents.Intent.APP_CONTROL:
        return _resolve_app_control(clean)

    if intent == intents.Intent.PHONE_CONTROL:
        message, directive = _resolve_phone_control(clean)
        return VoiceCommandResponse(
            intent=intent,
            text=message,
            priority="normal",
            directives=[directive],
        )

    if intent in {intents.Intent.SCENE, intents.Intent.OBSTACLE, intents.Intent.DISTANCE}:
        frame = (image_base64 or "").strip()
        if not frame:
            return VoiceCommandResponse(
                intent=intent,
                text="",
                priority="normal",
                action="speak",
                needs_frame=True,
            )
        try:
            return await _resolve_vision(intent, clean, frame, model)
        except Exception:
            return VoiceCommandResponse(
                intent=intent,
                text="I could not analyze the camera view right now. Please point the camera and try again.",
                priority="normal",
                action="speak",
            )

    try:
        return await _resolve_general(clean, turns, image_base64, model)
    except Exception:
        return VoiceCommandResponse(
            intent=intents.Intent.GENERAL,
            text="I had trouble answering that. Please try again.",
            priority="normal",
            action="speak",
        )