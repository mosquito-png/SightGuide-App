from typing import Any


class RedisCache:
    """Optional Redis adapter with graceful local fallback."""

    def __init__(self, url: str) -> None:
        self.url = url
        self._client: Any = None

    async def ping(self) -> bool:
        if self._client is None:
            return False
        return bool(await self._client.ping())

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
