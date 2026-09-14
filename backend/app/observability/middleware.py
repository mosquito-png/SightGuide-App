import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from app.observability.metrics import metrics


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Adds x-correlation-id to HTTP responses and records basic metrics.

    WebSocket upgrade requests are passed through untouched because
    BaseHTTPMiddleware cannot handle them and would otherwise return 403.
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Pass WebSocket connections directly to the next layer — do NOT
        # funnel them through BaseHTTPMiddleware.dispatch which lacks WS support.
        if scope["type"] == "websocket":
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)

    async def dispatch(self, request, call_next):
        started = time.perf_counter()
        correlation_id = request.headers.get("x-correlation-id", str(uuid4()))
        response = await call_next(request)
        response.headers["x-correlation-id"] = correlation_id
        metrics.observe(f"http.{request.method}.{request.url.path}", started)
        return response
