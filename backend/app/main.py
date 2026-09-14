from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.errors import ApplicationError, application_error_handler
from app.core.logging import configure_logging
from app.observability.middleware import CorrelationMiddleware
from app.api.v1 import guidance as v1_guidance, health as v1_health, metrics as v1_metrics
from app.routes import guidance, health, voice

configure_logging()
app = FastAPI(title="SightGuide API", version="0.1.0")
app.add_exception_handler(ApplicationError, application_error_handler)
app.add_middleware(CorrelationMiddleware)

# In development mode allow every origin so the Capacitor app running on a
# real phone (which sends origins like "capacitor://localhost",
# "https://localhost", or the phone's LAN IP) can reach the WebSocket and
# HTTP endpoints without manual origin whitelisting.
_is_dev = settings.environment.lower() in {"development", "dev", "local"}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _is_dev else list(settings.cors_origins),
    allow_credentials=False if _is_dev else True,  # credentials require explicit origin (not *)
    allow_methods=["*"],
    allow_headers=["*"],
    allow_origin_regex=(
        # Also allow any private-network IP (LAN) origin regardless of mode
        r"https?://(localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)(:\d+)?"
        if not _is_dev
        else None
    ),
)

from pathlib import Path
from fastapi.responses import FileResponse, JSONResponse

app.include_router(health.router, prefix="/api")
app.include_router(guidance.router, prefix="/api")
app.include_router(voice.router, prefix="/api")
app.include_router(v1_health.router, prefix="/api/v1")
app.include_router(v1_metrics.router, prefix="/api/v1")
app.include_router(v1_guidance.router, prefix="/api/v1")

@app.get("/download/apk", tags=["mobile"])
@app.get("/sightguide.apk", tags=["mobile"])
async def download_apk():
    candidates = [
        Path(__file__).resolve().parent.parent.parent / "frontend" / "public" / "sightguide.apk",
        Path(__file__).resolve().parent.parent.parent / "frontend" / "android" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk",
        Path(__file__).resolve().parent.parent.parent / "frontend" / "dist" / "sightguide.apk",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return FileResponse(
                path=candidate,
                media_type="application/vnd.android.package-archive",
                filename="sightguide.apk"
            )
    return JSONResponse(
        status_code=404,
        content={"error": "APK is currently building or not yet available."}
    )

