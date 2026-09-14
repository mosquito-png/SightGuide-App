import asyncio
import pytest

from app.assistant import command, intents
from app.schemas.voice import VoiceCommandResponse


@pytest.mark.parametrize(
    "phrase",
    [
        "emergency",
        "sos",
        "mayday",
        "i need help",
        "help me",
        "help me please",
        "call 911",
        "call emergency",
        "call an ambulance",
        "police immediately",
        "save me",
    ],
)
def test_emergency_phrases_classify_as_sos(phrase: str) -> None:
    intent = intents.classify_intent(phrase)
    assert intent == intents.Intent.SOS, f"Expected '{phrase}' to classify as SOS, got {intent}"


def test_sos_intent_priority_over_other_keywords() -> None:
    # "call 911" has "call", but should be classified as SOS
    assert intents.classify_intent("call 911") == intents.Intent.SOS
    assert intents.classify_intent("call emergency") == intents.Intent.SOS
    # "navigate to hospital emergency" - SOS keywords take priority
    assert intents.classify_intent("emergency help") == intents.Intent.SOS


def test_sos_command_resolution_produces_directive() -> None:
    result = asyncio.run(command.handle_voice_command("I need help emergency"))
    assert isinstance(result, VoiceCommandResponse)
    assert result.intent == intents.Intent.SOS
    assert result.priority == "urgent"
    assert len(result.directives) == 1
    assert result.directives[0].action == "sos"
    assert "emergency" in result.text.lower()


def test_sos_command_with_location_parameter() -> None:
    result = asyncio.run(
        command.handle_voice_command(
            "sos",
            lat=37.7749,
            lon=-122.4194,
            location_label="San Francisco, CA",
        )
    )
    assert result.intent == intents.Intent.SOS
    assert result.directives[0].action == "sos"
    assert result.directives[0].parameters.get("location") == "San Francisco, CA"
