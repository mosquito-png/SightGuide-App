from dataclasses import dataclass
import os
from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:

    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    environment: str = "development"
    auth_enabled: bool = False
    api_key: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    ai_timeout_seconds: float = 25.0
    google_maps_api_key: str = ""
    google_maps_map_id: str = ""
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_database: str = "sightguide"
    redis_url: str = "redis://localhost:6379/0"
    tool_timeout_seconds: float = 25.0
    max_retries: int = 2
    default_weather_lat: float = 40.7128
    default_weather_lon: float = -74.006
    default_weather_city: str = "New York"
    cors_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://localhost",
        "http://127.0.0.1",
        "capacitor://localhost",
        "ionic://localhost",
        "https://localhost",
    )

    @classmethod
    def from_env(cls) -> "Settings":
        origins = tuple(
            x.strip()
            for x in os.getenv(
                "CORS_ORIGINS",
                "http://localhost:5173,http://localhost,http://127.0.0.1,capacitor://localhost,ionic://localhost,https://localhost",
            ).split(",")
            if x.strip()
        )
        return cls(
            environment=os.getenv("ENVIRONMENT", "development"),
            auth_enabled=_bool("AUTH_ENABLED", False),
            api_key=os.getenv("SIGHTGUIDE_API_KEY", ""),
            gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
            gemini_model=os.getenv("GEMINI_MODEL", cls.gemini_model).strip(),
            openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            openai_model=os.getenv("OPENAI_MODEL", cls.openai_model).strip(),
            ai_timeout_seconds=float(os.getenv("AI_TIMEOUT_SECONDS", cls.ai_timeout_seconds)),
            google_maps_api_key=os.getenv("GOOGLE_MAPS_API_KEY", "").strip(),
            google_maps_map_id=os.getenv("GOOGLE_MAPS_MAP_ID", "").strip(),

            mongo_uri=os.getenv("MONGO_URI", cls.mongo_uri),
            mongo_database=os.getenv("MONGO_DATABASE", cls.mongo_database),
            redis_url=os.getenv("REDIS_URL", cls.redis_url),
            tool_timeout_seconds=float(os.getenv("TOOL_TIMEOUT_SECONDS", cls.tool_timeout_seconds)),
            max_retries=int(os.getenv("MAX_RETRIES", cls.max_retries)),
            default_weather_lat=float(os.getenv("DEFAULT_WEATHER_LAT", cls.default_weather_lat)),
            default_weather_lon=float(os.getenv("DEFAULT_WEATHER_LON", cls.default_weather_lon)),
            default_weather_city=os.getenv("DEFAULT_WEATHER_CITY", cls.default_weather_city),
            cors_origins=origins,
        )


settings = Settings.from_env()
