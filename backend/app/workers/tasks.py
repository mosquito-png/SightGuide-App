import asyncio
from collections.abc import Awaitable, Callable


async def run_background(task: Callable[[], Awaitable[object]]) -> asyncio.Task[object]:
    return asyncio.create_task(task())
