import asyncio
import logging
import pytest

from app.ai.providers import (
    FallbackLanguageModel,
    GeminiLanguageModel,
    OpenAILanguageModel,
    get_default_language_model,
)
import app.ai.providers as providers_mod
from app.core.config import Settings
from app.core.errors import UpstreamServiceError
from app.services.guidance import (
    describe_scene,
    detect_obstacles_and_objects,
    handle_voice_assistant_query,
    read_image_text,
)


class MockPrimarySuccess:
    def __init__(self, response: str = "Gemini primary response"):
        self.response = response
        self.call_count = 0
        self.last_prompt = None
        self.last_image = None
        self.api_key = "test_gemini_key"

    async def complete(self, prompt: str, image_base64: str | None = None) -> str:
        self.call_count += 1
        self.last_prompt = prompt
        self.last_image = image_base64
        return self.response


class MockPrimaryFails:
    def __init__(self, error: Exception | None = None):
        self.error = error or UpstreamServiceError("Gemini 500 Internal Server Error")
        self.call_count = 0
        self.api_key = "test_gemini_key"

    async def complete(self, prompt: str, image_base64: str | None = None) -> str:
        self.call_count += 1
        raise self.error


class MockPrimaryTimeout:
    def __init__(self):
        self.call_count = 0
        self.api_key = "test_gemini_key"

    async def complete(self, prompt: str, image_base64: str | None = None) -> str:
        self.call_count += 1
        await asyncio.sleep(10)  # Will trigger timeout
        return "Never returned"


class MockPrimaryEmpty:
    def __init__(self):
        self.call_count = 0
        self.api_key = "test_gemini_key"

    async def complete(self, prompt: str, image_base64: str | None = None) -> str:
        self.call_count += 1
        return "   "  # Empty whitespace


class MockFallbackSuccess:
    def __init__(self, response: str = "OpenAI fallback response"):
        self.response = response
        self.call_count = 0
        self.last_prompt = None
        self.last_image = None
        self.api_key = "test_openai_key"

    async def complete(self, prompt: str, image_base64: str | None = None) -> str:
        self.call_count += 1
        self.last_prompt = prompt
        self.last_image = image_base64
        return self.response


class MockFallbackFails:
    def __init__(self, error: Exception | None = None):
        self.error = error or UpstreamServiceError("OpenAI 429 Rate Limit")
        self.call_count = 0
        self.api_key = "test_openai_key"

    async def complete(self, prompt: str, image_base64: str | None = None) -> str:
        self.call_count += 1
        raise self.error


def test_fallback_uses_gemini_when_primary_succeeds(caplog):
    primary = MockPrimarySuccess(response="Clear walkway ahead from Gemini.")
    fallback = MockFallbackSuccess(response="Clear walkway from OpenAI.")
    model = FallbackLanguageModel(primary=primary, fallback=fallback)

    with caplog.at_level(logging.INFO):
        result = asyncio.run(model.complete("Describe the scene", image_base64="fakeimage123"))

    assert result == "Clear walkway ahead from Gemini."
    assert primary.call_count == 1
    assert fallback.call_count == 0
    assert primary.last_prompt == "Describe the scene"
    assert primary.last_image == "fakeimage123"
    assert any("primary provider: Gemini" in record.message for record in caplog.records)


def test_fallback_switches_to_openai_on_gemini_error(caplog):
    primary = MockPrimaryFails(UpstreamServiceError("Gemini quota exceeded (429)"))
    fallback = MockFallbackSuccess(response="Obstacle detected ahead from OpenAI.")
    model = FallbackLanguageModel(primary=primary, fallback=fallback)

    with caplog.at_level(logging.INFO):
        result = asyncio.run(model.complete("Check for hazards", image_base64="framedata456"))

    assert result == "Obstacle detected ahead from OpenAI."
    assert primary.call_count == 1
    assert fallback.call_count == 1
    assert fallback.last_prompt == "Check for hazards"
    assert fallback.last_image == "framedata456"
    assert any("falling back to OpenAI" in record.message for record in caplog.records)
    assert any("fallback provider: OpenAI" in record.message for record in caplog.records)


def test_fallback_switches_to_openai_on_gemini_empty_response(caplog):
    primary = MockPrimaryEmpty()
    fallback = MockFallbackSuccess(response="Valid response from OpenAI.")
    model = FallbackLanguageModel(primary=primary, fallback=fallback)

    with caplog.at_level(logging.INFO):
        result = asyncio.run(model.complete("Read this sign"))

    assert result == "Valid response from OpenAI."
    assert primary.call_count == 1
    assert fallback.call_count == 1
    assert any("falling back to OpenAI" in record.message for record in caplog.records)


def test_fallback_switches_to_openai_on_gemini_timeout(caplog):
    primary = MockPrimaryTimeout()
    fallback = MockFallbackSuccess(response="OpenAI response after Gemini timeout.")
    model = FallbackLanguageModel(primary=primary, fallback=fallback, timeout=0.05)

    with caplog.at_level(logging.INFO):
        result = asyncio.run(model.complete("Quick check"))

    assert result == "OpenAI response after Gemini timeout."
    assert primary.call_count == 1
    assert fallback.call_count == 1
    assert any("falling back to OpenAI" in record.message for record in caplog.records)


def test_fallback_handles_both_failing_with_error(monkeypatch):
    monkeypatch.setattr(providers_mod, "settings", Settings(environment="production"))
    primary = MockPrimaryFails(UpstreamServiceError("Gemini 503"))
    fallback = MockFallbackFails(UpstreamServiceError("OpenAI 500"))
    model = FallbackLanguageModel(primary=primary, fallback=fallback)

    with pytest.raises(UpstreamServiceError) as exc_info:
        asyncio.run(model.complete("Test prompt"))

    assert "Both AI providers failed" in str(exc_info.value)
    assert primary.call_count == 1
    assert fallback.call_count == 1


def test_fallback_returns_demo_mode_when_no_keys_in_dev(monkeypatch):
    monkeypatch.setattr(providers_mod, "settings", Settings(environment="development"))
    primary = MockPrimaryFails(UpstreamServiceError("Gemini API key is not configured"))
    primary.api_key = ""
    fallback = MockFallbackFails(UpstreamServiceError("OpenAI API key is not configured"))
    fallback.api_key = ""
    model = FallbackLanguageModel(primary=primary, fallback=fallback)

    result = asyncio.run(model.complete('{"summary": "test", "obstacles": []}'))
    assert "Demo Mode" in result


def test_no_keys_in_logs_and_security(caplog):
    fake_gemini_key = "AIzaSySecretGeminiKey999"
    fake_openai_key = "sk-proj-SecretOpenAIKey888"

    primary = MockPrimaryFails(UpstreamServiceError("Gemini connection error"))
    fallback = MockFallbackSuccess(response="Success")
    model = FallbackLanguageModel(primary=primary, fallback=fallback)

    with caplog.at_level(logging.DEBUG):
        asyncio.run(model.complete("Test security"))

    all_logs = "\n".join(record.message for record in caplog.records)
    assert fake_gemini_key not in all_logs
    assert fake_openai_key not in all_logs


def test_guidance_ocr_with_fallback():
    primary = MockPrimaryFails()
    fallback = MockFallbackSuccess(
        response=(
            '{\n'
            '  "summary": "The bottle says Aspirin 100mg.",\n'
            '  "text": "ASPIRIN 100mg Daily Dose",\n'
            '  "reading_type": "product_label",\n'
            '  "priority": "normal"\n'
            '}'
        )
    )
    fallback_model = FallbackLanguageModel(primary=primary, fallback=fallback)

    result = asyncio.run(read_image_text("fakeimagebase64data", model=fallback_model))
    assert result.reading_type == "product_label"
    assert "Aspirin" in result.summary
    assert "ASPIRIN 100mg" in result.text
    assert fallback.call_count == 1


def test_guidance_describe_scene_with_fallback():
    primary = MockPrimaryFails()
    fallback = MockFallbackSuccess(response="A quiet room with a doorway on your left.")
    fallback_model = FallbackLanguageModel(primary=primary, fallback=fallback)

    result = asyncio.run(describe_scene("Describe the room", model=fallback_model))
    assert "quiet room" in result.message
    assert fallback.call_count == 1


def test_guidance_voice_assistant_query_with_fallback():
    primary = MockPrimaryFails()
    fallback = MockFallbackSuccess(response="There is a water bottle in front of you.")
    fallback_model = FallbackLanguageModel(primary=primary, fallback=fallback)

    result = asyncio.run(
        handle_voice_assistant_query(
            question="What is that in front of me?",
            image_base64="fakeframedata",
            model=fallback_model,
        )
    )
    assert "water bottle" in result.answer
    assert fallback.call_count == 1
