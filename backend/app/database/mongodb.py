from typing import Any


class MongoRepository:
    """Optional Mongo adapter; construction does not connect during imports."""

    def __init__(self, uri: str, database: str) -> None:
        self.uri = uri
        self.database = database
        self._client: Any = None

    async def ping(self) -> bool:
        if self._client is None:
            return False
        await self._client.admin.command("ping")
        return True

    async def close(self) -> None:
        if self._client is not None:
            self._client.close()
