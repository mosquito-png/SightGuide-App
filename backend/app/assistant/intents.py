"""Canonical voice command intent classification.

This is the single source of truth for mapping a spoken transcript to an
intent. Client, server, and tests all rely on this module. The client never
re-implements intent matching -- it only executes device directives that the
backend returns, plus local interrupt handling (stop/cancel).
"""

import re

from app.services.guidance import NAVIGATION_INTENT_PATTERN


class Intent(str):
    TIME = "time"
    DATE = "date"
    WEATHER = "weather"
    CALL = "call"
    MESSAGE = "message"
    REMINDER = "reminder"
    SOS = "sos"
    CANCEL = "cancel"
    APP_CONTROL = "app_control"
    OPEN_APP = "open_app"
    SEARCH = "search"
    SCENE = "scene"
    OBSTACLE = "obstacle"
    DISTANCE = "distance"
    NAVIGATION = "navigation"
    GENERAL = "general"
    PHONE_CONTROL = "phone_control"


# Phone control & accessibility patterns (generic Android layer)
_PHONE_TYPE_PATTERNS = re.compile(
    r"^\s*(?:type[:\s]+|dictate[:\s]+|write[:\s]+|enter[:\s]+|input[:\s]+)\s*(?P<text>.+)$",
    re.IGNORECASE,
)

_PHONE_ORDINAL_PATTERNS = re.compile(
    r"^\s*(?:open|click|tap|select|play)\s+(?:the\s+)?(?P<ordinal>first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th|last|next)\s+(?P<target>[a-z0-9_\- ]+)",
    re.IGNORECASE,
)

_PHONE_CLICK_PATTERNS = re.compile(
    r"^\s*(?:click|tap|press|select)\s+(?:on\s+)?(?:the\s+)?(?P<target>[a-z0-9_\- '\"’]+)$",
    re.IGNORECASE,
)

_PHONE_SCROLL_PATTERNS = re.compile(
    r"^\s*(?:please\s+)?(scroll\s+down|scroll\s+up|swipe\s+up|swipe\s+down|swipe\s+left|swipe\s+right|scroll\s+to\s+top|scroll\s+to\s+bottom|page\s+down|page\s+up)\s*$",
    re.IGNORECASE,
)

_PHONE_NAV_PATTERNS = re.compile(
    r"^\s*(?:please\s+)?(go\s+back|back|go\s+home|home\s+screen|return\s+home|recent\s+apps|show\s+recents|open\s+recent\s+apps|open\s+notifications|quick\s+settings)\s*$",
    re.IGNORECASE,
)

_PHONE_MEDIA_PATTERNS = re.compile(
    r"^\s*(play|pause|resume|pause\s+video|play\s+video|resume\s+video|pause\s+music|play\s+music|stop\s+video)\s*$",
    re.IGNORECASE,
)

_PHONE_READ_SCREEN_PATTERNS = re.compile(
    r"\b(read\s+(?:the\s+)?screen|what(?:'s|\s+is)\s+on\s+(?:the|my)\s+screen|describe\s+(?:the\s+)?screen|list\s+buttons|list\s+options)\b",
    re.IGNORECASE,
)

_PHONE_SEARCH_PATTERNS = re.compile(
    r"^\s*(?:search(?:\s+for)?|find\s+in\s+app)\s+(?P<query>[^.?!\n]+)$",
    re.IGNORECASE,
)


# SOS must win over anything else ("call 911" is both call and sos -> sos).
_SOS_PATTERNS = re.compile(
    r"\b(sos|mayday|emergency|call 911|call emergency|i need help|need help|help me|"
    r"save me|ambulance|police (now|immediately)?|fire!)\b",
    re.IGNORECASE,
)

_CANCEL_PATTERNS = re.compile(
    r"\b(stop|stop listening|stop talking|cancel|never mind|nevermind|never mind now|"
    r"abort|pause|wait a second|be quiet|quiet|shut up|that('s| is) enough|go away)\b",
    re.IGNORECASE,
)

_SEARCH_PATTERNS = re.compile(
    r"\b(?:search(?:\s+(?:online|the\s+web|google))?(?:\s+for)?|google(?:\s+for)?|lookup|look\s+up|find\s+online)\b\s+(?P<query>.+)",
    re.IGNORECASE,
)
_SEARCH_BARE = re.compile(r"\b(search\s+online|search\s+(?:the\s+)?web|google\s+it)\b", re.IGNORECASE)

_OPEN_APP_PATTERNS = re.compile(
    r"\b(?:open|launch|start\s+app|switch\s+to|go\s+to)\b\s+(?P<target>[a-z0-9_\- ]+)",
    re.IGNORECASE,
)

_APP_CONTROL_PATTERNS = re.compile(
    r"\b(scan|scanning|auto[- ]?scan|continuous scan|"
    r"flip\s+camera|switch\s+camera|front\s+camera|back\s+camera|"
    r"toggle\s+camera|flip\s+the\s+camera|switch\s+the\s+camera|"
    r"mute|unmute|mute\s+voice|turn\s+off\s+voice|silence|volume\s+(up|down)|louder|quieter)\b",
    re.IGNORECASE,
)

_TIME_PATTERNS = re.compile(
    r"\b(what time|the time|current time|time is it|time now|"
    r"tell me the time|what's the time|whats the time)\b",
    re.IGNORECASE,
)

_DATE_PATTERNS = re.compile(
    r"\b(what('s| is) the date|the date today|today('s| is) date|current date|"
    r"what day is it|what day is today|what date|today's date|what is today)\b",
    re.IGNORECASE,
)

_WEATHER_PATTERNS = re.compile(
    r"\b(weather|weather today|forecast|temperature|rain|raining|rainy|sunny|cloudy|"
    r"humid|humidity|windy|wind speed|hot|cold|freezing|snow|snowing|precipitation)\b",
    re.IGNORECASE,
)

_CALL_PATTERNS = re.compile(
    r"\b(call|phone|ring up|dial)\b\s+(?P<target>.+)",
    re.IGNORECASE,
)
_CALL_BARE = re.compile(r"\b(call|phone|dial)\b", re.IGNORECASE)

_MESSAGE_PATTERNS = re.compile(
    r"\b(?:text|send\s+(?:a\s+)?(?:text|message)|message)\s+(?:to\s+)?(?P<target>.+)",
    re.IGNORECASE,
)
_MESSAGE_BARE = re.compile(r"^\s*(?:text|message|sms|send\s+(?:a\s+)?(?:text|message|sms))\s*$", re.IGNORECASE)

_REMINDER_PATTERNS = re.compile(
    r"\b(set\s+(?:a|an)?\s*(alarm|reminder|timer)|alarm|remind me|reminder|"
    r"wake me up|set a timer)\b",
    re.IGNORECASE,
)

_SCENE_PATTERNS = re.compile(
    r"\b(describe|what do you see|what('s| is) in front of me|what's in front|"
    r"whats in front|look around|what is around me|surroundings|what am i seeing|what is this|"
    r"read\s+(?:the\s+)?(?:label|text|sign|document|menu|book|paper|screen|notice|page|prescription|this)|"
    r"what\s+(?:does\s+(?:.+?\s+)?say|is\s+written(?:\s+here)?)|"
    r"transcribe)\b",
    re.IGNORECASE,
)

_OBSTACLE_PATTERNS = re.compile(
    r"\b(obstacle|obstacles|hazard|hazards|is\s+the\s+(?:path|way|road)\s+(?:clear|safe)|"
    r"something\s+(?:ahead|in\s+front|in\s+the\s+way)|anything\s+(?:ahead|in\s+front|in\s+the\s+way)|"
    r"blocking|blocked|in\s+the\s+way|safe\s+to\s+(walk|proceed|step|go)|is\s+it\s+clear|\brain's\s+clear\b"
    r"|step\s+(?:down|up)|drop.?off)\b",
    re.IGNORECASE,
)

_DISTANCE_PATTERNS = re.compile(
    r"\b(how far|distance|how close|depth|how deep|how far away|"
    r"how far is|estimate distance)\b",
    re.IGNORECASE,
)

_NAVIGATION_PATTERNS = NAVIGATION_INTENT_PATTERN


def _contains(pattern: re.Pattern[str], text: str) -> bool:
    return pattern.search(text) is not None


def classify_intent(text: str, context: list[tuple[str, str]] | None = None) -> str:
    """Classify a spoken command into an intent string."""
    clean = " ".join((text or "").strip().split())
    if not clean:
        return Intent.GENERAL

    # Media playback commands (e.g. "play", "pause", "resume")
    if _contains(_PHONE_MEDIA_PATTERNS, clean):
        return Intent.PHONE_CONTROL

    if _contains(_CANCEL_PATTERNS, clean):
        return Intent.CANCEL

    # Phone Accessibility Actions
    if _contains(_PHONE_TYPE_PATTERNS, clean):
        return Intent.PHONE_CONTROL
    if _contains(_PHONE_ORDINAL_PATTERNS, clean):
        return Intent.PHONE_CONTROL
    if _contains(_PHONE_SCROLL_PATTERNS, clean):
        return Intent.PHONE_CONTROL
    if _contains(_PHONE_NAV_PATTERNS, clean):
        return Intent.PHONE_CONTROL
    if _contains(_PHONE_READ_SCREEN_PATTERNS, clean):
        return Intent.PHONE_CONTROL

    # Explicit online search takes precedence for web search queries
    if re.search(r"\b(online|the\s+web|google)\b", clean, re.IGNORECASE) and (_contains(_SEARCH_PATTERNS, clean) or _contains(_SEARCH_BARE, clean)):
        return Intent.SEARCH

    # In-app search (e.g. "search for Minecraft", "find Minecraft")
    if _contains(_PHONE_SEARCH_PATTERNS, clean):
        return Intent.PHONE_CONTROL

    if _contains(_SEARCH_PATTERNS, clean) or _contains(_SEARCH_BARE, clean):
        return Intent.SEARCH

    # App Launching (before SOS so "open emergency" opens screen)
    if _contains(_OPEN_APP_PATTERNS, clean) and not _contains(_SCENE_PATTERNS, clean):
        target = extract_open_app_target(clean)
        if target:
            return Intent.OPEN_APP

    if _contains(_SOS_PATTERNS, clean):
        return Intent.SOS

    # UI Element Click / Tap
    if _contains(_PHONE_CLICK_PATTERNS, clean) and not _contains(_SCENE_PATTERNS, clean):
        return Intent.PHONE_CONTROL

    if _contains(_NAVIGATION_PATTERNS, clean):
        return Intent.NAVIGATION
    if _contains(_SCENE_PATTERNS, clean):
        return Intent.SCENE
    if _contains(_TIME_PATTERNS, clean):
        return Intent.TIME
    if _contains(_DATE_PATTERNS, clean):
        return Intent.DATE
    if _contains(_WEATHER_PATTERNS, clean):
        return Intent.WEATHER
    if _contains(_CALL_PATTERNS, clean) or _contains(_CALL_BARE, clean):
        return Intent.CALL
    if _contains(_MESSAGE_PATTERNS, clean) or _contains(_MESSAGE_BARE, clean):
        return Intent.MESSAGE
    if _contains(_REMINDER_PATTERNS, clean):
        return Intent.REMINDER
    if _contains(_APP_CONTROL_PATTERNS, clean):
        return Intent.APP_CONTROL
    if _contains(_OBSTACLE_PATTERNS, clean):
        return Intent.OBSTACLE
    if _contains(_DISTANCE_PATTERNS, clean):
        return Intent.DISTANCE

    # Follow-up fallbacks only kick in with real conversation history.
    context_text = " ".join(entry[1] for entry in (context or []))
    if "weather" in context_text or any(w in context_text for w in ("rain", "sunny", "cloudy", "forecast")):
        if re.search(r"\b(tomorrow|tonight|today|week|weekend|it\s+(?:is|will|going))\b", clean, re.IGNORECASE):
            return Intent.WEATHER

    return Intent.GENERAL


def extract_call_target(text: str) -> str | None:
    match = _CALL_PATTERNS.search(text)
    target = match.group("target") if match else None
    if target is None and _contains(_CALL_BARE, text):
        parts = re.split(r"\b(call|phone|ring up|dial)\b", text, maxsplit=1, flags=re.IGNORECASE)
        if len(parts) > 2:
            target = parts[-1].strip()
    clean = " ".join((target or "").strip().strip("?.,!").split())
    return clean or None


def extract_message_target(text: str) -> str | None:
    match = _MESSAGE_PATTERNS.search(text)
    if not match:
        return None
    target = match.group("target")
    return " ".join((target or "").strip().strip("?.,!").split()) or None


def extract_message_target_and_body(text: str) -> tuple[str | None, str | None]:
    raw_target = extract_message_target(text)
    if not raw_target:
        return None, None

    # Check for explicit separators like "saying ...", "that ...", "with message ..."
    sep_match = re.search(r"\b(?:saying|that|with\s+message|telling\s+(?:them|him|her)\s+(?:that)?)\b", raw_target, re.IGNORECASE)
    if sep_match:
        recipient = raw_target[:sep_match.start()].strip().strip(":,.-")
        body = raw_target[sep_match.end():].strip().strip(":,.-")
        return recipient or None, body or None

    # Check if first word is a common contact name or number, and the rest is message body
    words = raw_target.split()
    if len(words) > 1:
        first_word = words[0].lower()
        if first_word in {"mom", "dad", "mother", "father", "sister", "brother", "wife", "husband", "son", "daughter", "boss", "doctor", "friend", "home", "work"} or re.match(r"^\+?\d+$", words[0]):
            recipient = words[0]
            body = " ".join(words[1:]).strip()
            return recipient, body or None

    return raw_target, None


def extract_search_query(text: str) -> str | None:
    match = _SEARCH_PATTERNS.search(text)
    if match:
        query = match.group("query").strip().strip("?.,!.")
        if query.lower().startswith("for "):
            query = query[4:].strip()
        return query or None
    clean = re.sub(r"^(?:please\s+)?(?:search(?:\s+(?:online|the\s+web|google))?(?:\s+for)?|google(?:\s+for)?|lookup|look\s+up|find\s+online)\s*", "", text, flags=re.IGNORECASE).strip()
    return clean.strip("?.,!.") or None


def extract_open_app_target(text: str) -> str | None:
    match = _OPEN_APP_PATTERNS.search(text)
    if match:
        target = match.group("target").strip().strip("?.,!.")
        if target.lower() not in {"my eyes", "eyes", "a door", "door", "window"}:
            return target or None
    return None


def extract_reminder_text(text: str) -> str | None:
    target = extract_message_target(text)
    if target:
        return target
    match = _REMINDER_PATTERNS.search(text)
    if match:
        reminder = text[match.end():].strip().strip("?.,!.")
        return reminder or "a reminder"
    return "a reminder"


def extract_phone_control_info(text: str) -> dict[str, object]:
    """Extract structured details for phone control and UI navigation."""
    clean = " ".join((text or "").strip().split())

    # 1. Dictation / Typing
    m_type = _PHONE_TYPE_PATTERNS.match(clean)
    if m_type:
        text_val = m_type.group("text").strip().strip('"\'')
        return {"sub_action": "type", "text": text_val}

    # 2. Ordinal selection ("open the first video", "click the second button")
    m_ord = _PHONE_ORDINAL_PATTERNS.match(clean)
    if m_ord:
        ord_str = m_ord.group("ordinal").lower()
        ord_map = {
            "first": 1, "1st": 1,
            "second": 2, "2nd": 2,
            "third": 3, "3rd": 3,
            "fourth": 4, "4th": 4,
            "fifth": 5, "5th": 5,
            "last": -1, "next": 0,
        }
        ordinal = ord_map.get(ord_str, 1)
        target = m_ord.group("target").strip().strip("?.,!")
        return {"sub_action": "click", "target": target, "ordinal": ordinal}

    # 3. Media Controls ("play", "pause", "resume")
    m_med = _PHONE_MEDIA_PATTERNS.match(clean)
    if m_med:
        cmd = m_med.group(1).lower()
        media_cmd = "pause" if "pause" in cmd or "stop" in cmd else ("resume" if "resume" in cmd else "play")
        return {"sub_action": "media", "command": media_cmd, "target": media_cmd}

    # 4. In-App Search ("search for Minecraft", "find in app")
    m_srch = _PHONE_SEARCH_PATTERNS.match(clean)
    if m_srch and not re.search(r"\b(online|the\s+web|google)\b", clean, re.IGNORECASE):
        query = m_srch.group("query").strip().strip("?.,!")
        return {"sub_action": "search", "query": query, "target": query}

    # 5. Scrolling
    m_scroll = _PHONE_SCROLL_PATTERNS.match(clean)
    if m_scroll:
        phrase = m_scroll.group(1).lower()
        if "up" in phrase:
            direction = "up"
        elif "top" in phrase:
            direction = "top"
        elif "bottom" in phrase:
            direction = "bottom"
        elif "left" in phrase:
            direction = "left"
        elif "right" in phrase:
            direction = "right"
        else:
            direction = "down"
        return {"sub_action": "scroll", "direction": direction}

    # 6. Global Navigation
    m_nav = _PHONE_NAV_PATTERNS.match(clean)
    if m_nav:
        phrase = m_nav.group(1).lower()
        if "back" in phrase:
            action = "back"
        elif "home" in phrase:
            action = "home"
        elif "notification" in phrase:
            action = "notifications"
        elif "settings" in phrase:
            action = "quick_settings"
        else:
            action = "recents"
        return {"sub_action": "global_nav", "global_action": action}

    # 7. Screen Reading
    if _PHONE_READ_SCREEN_PATTERNS.match(clean):
        return {"sub_action": "read_screen"}

    # 8. UI Element Click / Tap
    m_click = _PHONE_CLICK_PATTERNS.match(clean)
    if m_click:
        target = m_click.group("target").strip().strip("?.,!")
        return {"sub_action": "click", "target": target}

    return {"sub_action": "unknown", "text": clean}
