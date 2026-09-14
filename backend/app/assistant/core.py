from app.assistant import command as command_service
from app.assistant.response import build_response
from app.assistant.permissions import PermissionManager
from app.schemas.guidance import GuidanceResponse, VisionDetectionResponse, VoiceAssistantQueryResponse
from app.schemas.voice import VoiceCommandResponse
from app.tools.registry import ToolRegistry
from app.tools.executor import ToolExecutor


class AssistantCore:
    def __init__(self, tools: ToolRegistry) -> None:
        self.tools = tools
        self.permissions = PermissionManager()
        self.executor = ToolExecutor()

    async def handle_command(
        self,
        text: str,
        context: list[tuple[str, str]] | None = None,
        lat: float | None = None,
        lon: float | None = None,
        location_label: str | None = None,
        image_base64: str | None = None,
    ) -> VoiceCommandResponse:
        return await command_service.handle_voice_command(
            text=text,
            context=context,
            lat=lat,
            lon=lon,
            location_label=location_label,
            image_base64=image_base64,
        )

    async def handle_text(self, text: str) -> GuidanceResponse:
        tool = self.tools.get("vision.voice_assistant")
        if not self.permissions.can_execute(tool.name):
            raise PermissionError(f"Permission denied for tool: {tool.name}")
        result = await self.executor.execute(
            tool,
            {"question": text, "context": "general"},
            self.tools.policy(tool.name),
        )
        if hasattr(result, "answer"):
            return build_response(
                GuidanceResponse(
                    message=str(result.answer),
                    priority=str(getattr(result, "priority", "normal")),
                )
            )
        return build_response(result)

    async def handle_vision(
        self,
        image_base64: str,
        mode: str = "navigation",
        prompt_override: str | None = None,
    ) -> VisionDetectionResponse:
        tool = self.tools.get("vision.detect_obstacles")
        if not self.permissions.can_execute(tool.name):
            raise PermissionError(f"Permission denied for tool: {tool.name}")
        result = await self.executor.execute(
            tool,
            {"image_base64": image_base64, "mode": mode, "prompt_override": prompt_override},
            self.tools.policy(tool.name),
        )
        return result