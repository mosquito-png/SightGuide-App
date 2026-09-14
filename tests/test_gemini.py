import asyncio

from backend.app.services.guidance import describe_scene, detect_obstacles_and_objects, read_image_text


class FakeGemini:
    def __init__(self) -> None:
        self.prompt = ""
        self.image = ""

    async def complete(self, prompt: str, image_base64: str | None = None) -> str:
        self.prompt = prompt
        self.image = image_base64 or ""
        if "SightGuide OCR" in prompt or "optical character" in prompt:
            return (
                '{\n'
                '  "summary": "The sign says Exit to Market Street.",\n'
                '  "text": "EXIT\\nMarket Street\\nPlatform 2",\n'
                '  "reading_type": "sign",\n'
                '  "priority": "normal"\n'
                '}'
            )
        if image_base64:
            return (
                '{\n'
                '  "summary": "Vehicle detected on the right at 2 o\'clock, 4 meters away.",\n'
                '  "priority": "warning",\n'
                '  "obstacles": [\n'
                '    {\n'
                '      "label": "car",\n'
                '      "location_clock": "2 o\'clock",\n'
                '      "distance": "4 meters",\n'
                '      "hazard_level": "medium"\n'
                '    }\n'
                '  ]\n'
                '}'
            )
        return "There is a laptop on a desk in front of you."


def test_guidance_uses_gemini_result() -> None:
    model = FakeGemini()
    result = asyncio.run(describe_scene("There is a laptop on a desk in front of me.", model))
    assert result.message == "There is a laptop on a desk in front of you."
    assert "There is a laptop on a desk in front of me." in model.prompt


def test_obstacle_detection_with_vision_gemini() -> None:
    model = FakeGemini()
    result = asyncio.run(detect_obstacles_and_objects("base64imagepayload123", mode="navigation", model=model))
    assert result.priority == "warning"
    assert len(result.obstacles) == 1
    assert result.obstacles[0].label == "car"
    assert result.obstacles[0].location_clock == "2 o'clock"
    assert "Vehicle detected" in result.summary
    assert model.image == "base64imagepayload123"


def test_read_image_text_with_gemini() -> None:
    model = FakeGemini()
    result = asyncio.run(read_image_text("base64signimage789", model=model))
    assert result.reading_type == "sign"
    assert "Exit to Market Street" in result.summary
    assert "EXIT\nMarket Street" in result.text
    assert model.image == "base64signimage789"


def test_reading_mode_in_detect_obstacles_routes_to_ocr() -> None:
    model = FakeGemini()
    result = asyncio.run(detect_obstacles_and_objects("base64signimage789", mode="reading", model=model))
    assert "Exit to Market Street" in result.summary
    assert result.extracted_text == "EXIT\nMarket Street\nPlatform 2"

