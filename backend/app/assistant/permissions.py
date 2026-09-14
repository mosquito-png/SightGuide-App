class PermissionManager:
    def can_execute(self, tool_name: str) -> bool:
        # Safe read-only tools are allowed in the initial implementation.
        return tool_name in {"vision.describe_scene", "vision.detect_obstacles", "vision.voice_assistant"}


