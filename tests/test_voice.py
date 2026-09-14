import re

from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def voice_command(text: str, **overrides) -> dict:
    payload = {"text": text}
    payload.update(overrides)
    response = client.post("/api/voice/command", json=payload)
    assert response.status_code == 200
    return response.json()


def test_time_intent_returns_actual_current_time() -> None:
    result = voice_command("What's the time?")
    assert result["intent"] == "time"
    assert re.match(r"^It is \d{1,2}:\d{2} (AM|PM)\.$", result["text"])
    assert result["text"] != "What's the time?"


def test_date_intent_returns_actual_current_date() -> None:
    result = voice_command("What's today's date?")
    assert result["intent"] == "date"
    assert re.match(r"^Today is \w+, \w+ \d{1,2}(st|nd|rd|th), \d{4}\.$", result["text"])
    assert result["text"] != "What's today's date?"


def test_call_intent_returns_device_directive(monkeypatch) -> None:
    result = voice_command("Call Mom")
    assert result["intent"] == "call"
    assert result["directives"] == [{"action": "call", "value": "Mom", "parameters": {}}]


def test_message_intent_returns_device_directive() -> None:
    result = voice_command("Text Julie saying I'm on my way")
    assert result["intent"] == "message"
    assert result["directives"][0]["action"] == "message"
    assert "Julie" in result["directives"][0]["value"]


def test_reminder_intent_returns_timed_directive() -> None:
    result = voice_command("set a reminder to take medicine in 10 minutes")
    assert result["intent"] == "reminder"
    directive = result["directives"][0]
    assert directive["action"] == "reminder"
    assert directive["parameters"]["seconds"] == 600


def test_sos_intent_returns_urgent_directive() -> None:
    result = voice_command("I need help", lat=40.7, lon=-74.0)
    assert result["intent"] == "sos"
    assert result["priority"] == "urgent"
    assert result["directives"][0]["action"] == "sos"


def test_cancel_intent_stops_operation() -> None:
    result = voice_command("Stop")
    assert result["intent"] == "cancel"
    assert result["action"] == "stop_all"


def test_navigation_intent_starts_walking_route() -> None:
    result = voice_command("Navigate to the nearest pharmacy")
    assert result["intent"] == "navigation"
    assert result["action"] == "start_navigation"
    assert result["navigation_destination"] == "the nearest pharmacy"


def test_general_question_returns_llm_answer(monkeypatch) -> None:
    async def fake_answer(question, image_base64=None, context="general", context_turns=None, model=None):
        from backend.app.schemas.guidance import VoiceAssistantQueryResponse

        return VoiceAssistantQueryResponse(
            answer="Machine learning is the study of computers learning from data.",
            action="speak",
            priority="normal",
        )

    monkeypatch.setattr("app.services.guidance.handle_voice_assistant_query", fake_answer)
    result = voice_command("What is machine learning?")
    assert result["intent"] == "general"
    assert result["text"] == "Machine learning is the study of computers learning from data."
    assert result["text"] != "What is machine learning?"


def test_scene_intent_requests_camera_frame_first() -> None:
    result = voice_command("What's in front of me?")
    assert result["intent"] == "scene"
    assert result["needs_frame"] is True


def test_obstacle_intent_with_frame_returns_vision_analysis(monkeypatch) -> None:
    async def fake_detect(image_base64, mode="navigation", prompt_override=None, model=None):
        from backend.app.schemas.guidance import DetectedObstacle, VisionDetectionResponse

        return VisionDetectionResponse(
            summary="Caution: car detected ahead.",
            priority="warning",
            obstacles=[
                DetectedObstacle(
                    label="car",
                    location_clock="2 o'clock",
                    distance="4 meters",
                    hazard_level="medium",
                )
            ],
        )

    monkeypatch.setattr("app.services.guidance.detect_obstacles_and_objects", fake_detect)
    result = voice_command("Is there an obstacle ahead?", image_base64="base64fake12345")
    assert result["intent"] == "obstacle"
    assert "car" in result["text"]
    assert "car" in result["detected_items"]


def test_distance_intent_with_frame_returns_nearest_object(monkeypatch) -> None:
    async def fake_detect(image_base64, mode="navigation", prompt_override=None, model=None):
        from backend.app.schemas.guidance import DetectedObstacle, VisionDetectionResponse

        return VisionDetectionResponse(
            summary="Detected 1 object.",
            priority="normal",
            obstacles=[
                DetectedObstacle(
                    label="chair",
                    location_clock="12 o'clock",
                    distance="very close",
                    hazard_level="medium",
                )
            ],
        )

    monkeypatch.setattr("app.services.guidance.detect_obstacles_and_objects", fake_detect)
    result = voice_command("How far is that?", image_base64="base64fake12345")
    assert result["intent"] == "distance"
    assert "chair" in result["text"]


def test_weather_rain_followup_uses_context_without_llm(monkeypatch) -> None:
    async def fake_weather(lat, lon):
        return {
            "current": {
                "temperature_2m": 11.6,
                "apparent_temperature": 9.0,
                "relative_humidity_2m": 74,
                "precipitation": 0.0,
                "weather_code": 3,
                "wind_speed_10m": 12.4,
            },
            "daily": {"precipitation_probability_max": [40.0]},
        }

    monkeypatch.setattr("app.services.weather.fetch_weather", fake_weather)
    result = voice_command(
        "Will it rain?",
        lat=35.2,
        lon=-80.9,
    )
    assert result["intent"] == "weather"
    assert "rain" in result["text"].lower()


def test_weather_returns_real_open_meteo_data() -> None:
    """Live integration: real weather API data must be returned when online."""
    import pytest

    try:
        import httpx

        response = httpx.get(
            "https://api.open-meteo.com/v1/forecast",
            params={"latitude": 40.7, "longitude": -74.0, "current": "temperature_2m,weather_code", "forecast_days": 1},
            timeout=8.0,
        )
        response.raise_for_status()
    except Exception:
        pytest.skip("Open-Meteo weather API unreachable in this environment")
    result = voice_command("How's the weather today?", lat=40.7, lon=-74.0)
    assert result["intent"] == "weather"
    assert len(result["text"]) > 10
