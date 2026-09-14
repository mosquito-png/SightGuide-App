import asyncio
from app.assistant import intents
from app.assistant.command import handle_voice_command


def test_phone_control_typing_intent() -> None:
    cmd = "Type: I'll call you later"
    classified = intents.classify_intent(cmd)
    assert classified == intents.Intent.PHONE_CONTROL

    res = asyncio.run(handle_voice_command(cmd))
    assert res.intent == intents.Intent.PHONE_CONTROL
    assert "Typing: I'll call you later" in res.text
    assert len(res.directives) == 1
    assert res.directives[0].action == "phone_control"
    assert res.directives[0].parameters["sub_action"] == "type"
    assert res.directives[0].parameters["text"] == "I'll call you later"


def test_phone_control_ordinal_click_intent() -> None:
    cmd = "Open the first video"
    classified = intents.classify_intent(cmd)
    assert classified == intents.Intent.PHONE_CONTROL

    res = asyncio.run(handle_voice_command(cmd))
    assert res.intent == intents.Intent.PHONE_CONTROL
    assert "first video" in res.text
    assert len(res.directives) == 1
    assert res.directives[0].parameters["sub_action"] == "click"
    assert res.directives[0].parameters["target"] == "video"
    assert res.directives[0].parameters["ordinal"] == 1


def test_phone_control_media_playback_intent() -> None:
    for phrase in ["Play", "Pause", "Resume"]:
        classified = intents.classify_intent(phrase)
        assert classified == intents.Intent.PHONE_CONTROL

        res = asyncio.run(handle_voice_command(phrase))
        assert res.intent == intents.Intent.PHONE_CONTROL
        assert len(res.directives) == 1
        assert res.directives[0].parameters["sub_action"] == "media"


def test_phone_control_scrolling_intent() -> None:
    for phrase in ["Scroll down", "Scroll up", "Swipe down"]:
        classified = intents.classify_intent(phrase)
        assert classified == intents.Intent.PHONE_CONTROL

        res = asyncio.run(handle_voice_command(phrase))
        assert res.intent == intents.Intent.PHONE_CONTROL
        assert len(res.directives) == 1
        assert res.directives[0].parameters["sub_action"] == "scroll"


def test_phone_control_global_nav_intent() -> None:
    for phrase in ["Go back", "Go home", "Recent apps"]:
        classified = intents.classify_intent(phrase)
        assert classified == intents.Intent.PHONE_CONTROL

        res = asyncio.run(handle_voice_command(phrase))
        assert res.intent == intents.Intent.PHONE_CONTROL
        assert len(res.directives) == 1
        assert res.directives[0].parameters["sub_action"] == "global_nav"


def test_phone_control_in_app_search_intent() -> None:
    cmd = "Search for Minecraft"
    classified = intents.classify_intent(cmd)
    assert classified == intents.Intent.PHONE_CONTROL

    res = asyncio.run(handle_voice_command(cmd))
    assert res.intent == intents.Intent.PHONE_CONTROL
    assert len(res.directives) == 1
    assert res.directives[0].parameters["sub_action"] == "search"
    assert res.directives[0].parameters["query"] == "Minecraft"


def test_phone_control_read_screen_intent() -> None:
    cmd = "What is on my screen"
    classified = intents.classify_intent(cmd)
    assert classified == intents.Intent.PHONE_CONTROL

    res = asyncio.run(handle_voice_command(cmd))
    assert res.intent == intents.Intent.PHONE_CONTROL
    assert len(res.directives) == 1
    assert res.directives[0].parameters["sub_action"] == "read_screen"
