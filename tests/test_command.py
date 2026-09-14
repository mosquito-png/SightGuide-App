import asyncio

from app.assistant import command, intents
from app.schemas.voice import VoiceCommandResponse



def test_classify_priority_sos_wins() -> None:
    assert intents.classify_intent("call 911 help me") == intents.Intent.SOS


def test_classify_cancel() -> None:
    assert intents.classify_intent("stop listening") == intents.Intent.CANCEL


def test_classify_time_and_date() -> None:
    assert intents.classify_intent("what time is it") == intents.Intent.TIME
    assert intents.classify_intent("give me today's date") == intents.Intent.DATE


def test_classify_device_intents() -> None:
    assert intents.classify_intent("call mom") == intents.Intent.CALL
    assert intents.classify_intent("text sarah") == intents.Intent.MESSAGE
    assert intents.classify_intent("set an alarm for 7am") == intents.Intent.REMINDER
    assert intents.classify_intent("navigate to the market") == intents.Intent.NAVIGATION


def test_classify_vision_intents() -> None:
    assert intents.classify_intent("what is in front of me") == intents.Intent.SCENE
    assert intents.classify_intent("is there an obstacle ahead") == intents.Intent.OBSTACLE
    assert intents.classify_intent("how far away is that") == intents.Intent.DISTANCE


def test_classify_weather_and_followup_context() -> None:
    assert intents.classify_intent("how is the weather today") == intents.Intent.WEATHER
    assert intents.classify_intent("will it rain") == intents.Intent.WEATHER
    followup = intents.classify_intent(
        "what about tomorrow",
        context=[("user", "how is the weather today"), ("assistant", "It is sunny and hot today.")],
    )
    assert followup == intents.Intent.WEATHER


def test_classify_general_no_llm_rewrite() -> None:
    assert intents.classify_intent("what is machine learning") == intents.Intent.GENERAL


def test_extract_call_and_message_targets() -> None:
    assert intents.extract_call_target("call mom") == "mom"
    assert intents.extract_call_target("please call 555-012-3456") == "555-012-3456"
    assert intents.extract_message_target("text sofia saying hello") == "sofia saying hello"
    assert intents.extract_message_target("send a message to dad") == "dad"


def test_time_answer_is_spoken_not_echoed() -> None:
    result = asyncio.run(command.handle_voice_command("what's the time?"))
    assert isinstance(result, VoiceCommandResponse)
    assert result.intent == intents.Intent.TIME
    assert result.text != "what's the time?"
    assert result.text.startswith("It is ")


def test_date_answer_is_spoken_not_echoed() -> None:
    result = asyncio.run(command.handle_voice_command("what's today's date?"))
    assert result.intent == intents.Intent.DATE
    assert result.text.startswith("Today is ")


def test_call_produces_directive() -> None:
    result = asyncio.run(command.handle_voice_command("Call Mom"))
    assert result.intent == intents.Intent.CALL
    assert result.directives[0].action == "call"
    assert result.directives[0].value == "Mom"



def test_general_uses_llm_and_keeps_context(monkeypatch) -> None:
    captured = {}

    async def fake_answer(question, image_base64=None, context="general", context_turns=None, model=None):
        captured["question"] = question
        captured["turns"] = context_turns

        class _Resp:
            answer = "You asked three separate questions and I answered each one."
            priority = "normal"
            action = "speak"

        return _Resp()

    monkeypatch.setattr("app.services.guidance.handle_voice_assistant_query", fake_answer)
    result = asyncio.run(
        command.handle_voice_command(
            "What was my first question?",
            context=[("user", "what is machine learning"), ("assistant", "It is the study of data.")],
        )
    )
    assert result.intent == intents.Intent.GENERAL
    assert captured["turns"] == [
        ("user", "what is machine learning"),
        ("assistant", "It is the study of data."),
    ]
    assert result.text != "What was my first question?"


def test_vision_scene_asks_for_frame_first() -> None:
    result = asyncio.run(command.handle_voice_command("what's in front of me?"))
    assert result.intent == intents.Intent.SCENE
    assert result.needs_frame is True


def test_obstacle_vision_analysis(monkeypatch) -> None:
    async def fake_detect(image_base64, mode="navigation", prompt_override=None, model=None):
        from app.schemas.guidance import DetectedObstacle, VisionDetectionResponse

        return VisionDetectionResponse(
            summary="Caution: staircase ahead.",
            priority="urgent",
            obstacles=[
                DetectedObstacle(
                    label="stairs",
                    location_clock="12 o'clock",
                    distance="close",
                    hazard_level="urgent",
                )
            ],
        )

    monkeypatch.setattr("app.services.guidance.detect_obstacles_and_objects", fake_detect)
    result = asyncio.run(
        command.handle_voice_command("is there an obstacle ahead?", image_base64="data:image/jpeg;base64,aW1n")
    )
    assert result.intent == intents.Intent.OBSTACLE
    assert result.priority == "urgent"
    assert "staircase" in result.text


def test_weather_question_ignores_llm(monkeypatch) -> None:
    async def fake_fetch(lat, lon):
        return {
            "current": {
                "temperature_2m": 8.4,
                "apparent_temperature": 6.1,
                "relative_humidity_2m": 81,
                "precipitation": 0.0,
                "weather_code": 2,
                "wind_speed_10m": 7.0,
            },
            "daily": {"precipitation_probability_max": [10.0]},
        }

    monkeypatch.setattr("app.services.weather.fetch_weather", fake_fetch)
    result = asyncio.run(command.handle_voice_command("what's the weather today?", lat=48.8, lon=2.3))
    assert result.intent == intents.Intent.WEATHER
    assert "degrees" in result.text


def test_weather_unreachable_returns_graceful_message(monkeypatch) -> None:
    async def fake_fetch(lat, lon):
        raise RuntimeError("network down")

    monkeypatch.setattr("app.services.weather.fetch_weather", fake_fetch)
    result = asyncio.run(command.handle_voice_command("what's the weather", lat=48.8, lon=2.3))
    assert result.intent == intents.Intent.WEATHER
    assert "weather service" in result.text


def test_vision_failure_recovers_with_graceful_message(monkeypatch) -> None:
    async def fake_detect(image_base64, mode="navigation", prompt_override=None, model=None):
        raise RuntimeError("yolo crash")

    monkeypatch.setattr("app.services.guidance.detect_obstacles_and_objects", fake_detect)
    result = asyncio.run(
        command.handle_voice_command("is there a hazard ahead?", image_base64="data:image/jpeg;base64,aW1n")
    )
    assert result.intent == intents.Intent.OBSTACLE
    assert "try again" in result.text


def test_app_control_scan_mute_and_camera() -> None:
    result = asyncio.run(command.handle_voice_command("start continuous scanning"))
    assert result.intent == intents.Intent.APP_CONTROL
    assert result.directives[0].action == "start_scan"

    result = asyncio.run(command.handle_voice_command("flip the camera"))
    assert result.intent == intents.Intent.APP_CONTROL
    assert result.directives[0].action == "switch_camera"

    result = asyncio.run(command.handle_voice_command("mute"))
    assert result.intent == intents.Intent.APP_CONTROL
    assert result.directives[0].action == "mute"

    assert intents.classify_intent("stop scanning") == intents.Intent.CANCEL


def test_search_online_intent_and_directive() -> None:
    assert intents.classify_intent("search online for nearest pharmacy") == intents.Intent.SEARCH
    assert intents.classify_intent("google weather in Tokyo") == intents.Intent.SEARCH
    assert intents.classify_intent("find online Italian restaurants") == intents.Intent.SEARCH

    result = asyncio.run(command.handle_voice_command("search online for coffee shop"))
    assert result.intent == intents.Intent.SEARCH
    assert len(result.directives) == 1
    assert result.directives[0].action == "search_web"
    assert result.directives[0].value == "coffee shop"
    assert "google.com/search?q=coffee+shop" in str(result.directives[0].parameters.get("url"))
    assert "coffee shop" in result.text


def test_open_app_internal_screens() -> None:
    assert intents.classify_intent("open camera") == intents.Intent.OPEN_APP
    assert intents.classify_intent("open settings") == intents.Intent.OPEN_APP
    assert intents.classify_intent("open navigation") == intents.Intent.OPEN_APP
    assert intents.classify_intent("open emergency") == intents.Intent.OPEN_APP

    res_cam = asyncio.run(command.handle_voice_command("open camera"))
    assert res_cam.intent == intents.Intent.OPEN_APP
    assert res_cam.directives[0].action == "open_screen"
    assert res_cam.directives[0].value == "vision"

    res_set = asyncio.run(command.handle_voice_command("open settings"))
    assert res_set.intent == intents.Intent.OPEN_APP
    assert res_set.directives[0].action == "open_screen"
    assert res_set.directives[0].value == "settings"


def test_open_external_apps() -> None:
    assert intents.classify_intent("open whatsapp") == intents.Intent.OPEN_APP
    assert intents.classify_intent("open youtube") == intents.Intent.OPEN_APP
    assert intents.classify_intent("open spotify") == intents.Intent.OPEN_APP

    res_wa = asyncio.run(command.handle_voice_command("open whatsapp"))
    assert res_wa.intent == intents.Intent.OPEN_APP
    assert res_wa.directives[0].action == "open_external"
    assert res_wa.directives[0].value == "WhatsApp"
    assert "wa.me" in str(res_wa.directives[0].parameters.get("url"))

    res_yt = asyncio.run(command.handle_voice_command("open youtube"))
    assert res_yt.intent == intents.Intent.OPEN_APP
    assert res_yt.directives[0].action == "open_external"
    assert res_yt.directives[0].value == "YouTube"


def test_message_with_body_extraction() -> None:
    result = asyncio.run(command.handle_voice_command("text Dad I am on my way"))
    assert result.intent == intents.Intent.MESSAGE
    assert result.directives[0].action == "message"
    assert result.directives[0].value == "Dad"
    assert result.directives[0].parameters.get("body") == "I am on my way"
    assert "I am on my way" in result.text

    result2 = asyncio.run(command.handle_voice_command("send a message to Mom saying hello there"))
    assert result2.intent == intents.Intent.MESSAGE
    assert result2.directives[0].value == "Mom"
    assert result2.directives[0].parameters.get("body") == "hello there"


def test_ocr_voice_command_routing(monkeypatch) -> None:
    from app.schemas.guidance import OCRReadTextResponse

    # 1. Without a frame, asks client to capture frame
    assert intents.classify_intent("read this") == intents.Intent.SCENE
    assert intents.classify_intent("read text") == intents.Intent.SCENE
    assert intents.classify_intent("what does this sign say") == intents.Intent.SCENE
    assert intents.classify_intent("read document") == intents.Intent.SCENE

    res_no_frame = asyncio.run(command.handle_voice_command("what does this sign say"))
    assert res_no_frame.intent == intents.Intent.SCENE
    assert res_no_frame.needs_frame is True

    # 2. With frame provided, routes to OCR and returns extracted_text
    async def fake_read_text(image_base64, focus_area=None, prompt_override=None, model=None):
        return OCRReadTextResponse(
            summary="The sign reads: Emergency Exit Only.",
            text="EMERGENCY EXIT ONLY",
            reading_type="sign",
            priority="warning",
            timestamp="2026-09-09T12:00:00Z",
        )

    monkeypatch.setattr("app.services.guidance.read_image_text", fake_read_text)
    res_with_frame = asyncio.run(
        command.handle_voice_command("what does this sign say", image_base64="fakeimageframe123")
    )
    assert res_with_frame.intent == intents.Intent.SCENE
    assert "Emergency Exit" in res_with_frame.text
    assert res_with_frame.extracted_text == "EMERGENCY EXIT ONLY"
