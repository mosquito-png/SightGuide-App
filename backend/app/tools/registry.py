from typing import Any

from app.schemas.guidance import GuidanceResponse, VisionDetectionResponse
from app.services import guidance as guidance_service
from app.tools.base import Tool
from app.tools.policy import ToolPolicy


class DescribeSceneTool(Tool):
    name = "vision.describe_scene"

    async def execute(self, arguments: dict[str, Any]) -> GuidanceResponse:
        scene = str(arguments["scene"]).strip()
        if not scene:
            raise ValueError("scene must not be empty")
        return GuidanceResponse(message=f"Scene received: {scene}", priority="normal")


class DetectObstaclesTool(Tool):
    name = "vision.detect_obstacles"

    async def execute(self, arguments: dict[str, Any]) -> VisionDetectionResponse:
        image = str(arguments.get("image_base64", "")).strip()
        if not image:
            raise ValueError("image_base64 must not be empty")
        mode = str(arguments.get("mode", "navigation"))
        prompt = arguments.get("prompt_override")
        return await guidance_service.detect_obstacles_and_objects(image, mode=mode, prompt_override=prompt)


class VoiceAssistantTool(Tool):
    name = "vision.voice_assistant"

    async def execute(self, arguments: dict[str, Any]):
        question = str(arguments.get("question", "")).strip()
        if not question:
            raise ValueError("question must not be empty")
        image = arguments.get("image_base64")
        context = str(arguments.get("context", "general"))
        return await guidance_service.handle_voice_assistant_query(question, image_base64=image, context=context)


class ReadTextTool(Tool):
    name = "vision.read_text"

    async def execute(self, arguments: dict[str, Any]):
        image = str(arguments.get("image_base64", "")).strip()
        if not image:
            raise ValueError("image_base64 must not be empty")
        focus = arguments.get("focus_area")
        prompt = arguments.get("prompt_override")
        return await guidance_service.read_image_text(image, focus_area=focus, prompt_override=prompt)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {
            DescribeSceneTool.name: DescribeSceneTool(),
            DetectObstaclesTool.name: DetectObstaclesTool(),
            VoiceAssistantTool.name: VoiceAssistantTool(),
            ReadTextTool.name: ReadTextTool(),
        }
        self._policies = {
            DescribeSceneTool.name: ToolPolicy(),
            DetectObstaclesTool.name: ToolPolicy(),
            VoiceAssistantTool.name: ToolPolicy(),
            ReadTextTool.name: ToolPolicy(),
        }


    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as error:
            raise ValueError(f"Unknown tool: {name}") from error

    def policy(self, name: str) -> ToolPolicy:
        return self._policies[name]

