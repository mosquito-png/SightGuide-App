import asyncio
from typing import Any

from app.core.config import settings
from app.tools.base import Tool
from app.tools.policy import PolicyManager, ToolPolicy


class ToolExecutor:
    def __init__(self, policy: PolicyManager | None = None) -> None:
        self.policy = policy or PolicyManager()

    async def execute(self, tool: Tool, arguments: dict[str, Any], policy: ToolPolicy) -> Any:
        self.policy.authorize(policy)
        attempts = max(0, settings.max_retries) + 1
        for attempt in range(attempts):
            try:
                return await asyncio.wait_for(tool.execute(arguments), timeout=settings.tool_timeout_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                if attempt == attempts - 1:
                    raise
                await asyncio.sleep(min(0.1 * (2**attempt), 1.0))
        raise RuntimeError("Tool execution exhausted")
