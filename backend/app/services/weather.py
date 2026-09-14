"""Real weather data via the Open-Meteo API (no API key required).

Open-Meteo provides current conditions and per-day precipitation probability
using only latitude/longitude. The backend is the single weather provider so
the frontend never needs its own key or duplicate logic.
"""

from dataclasses import asdict, dataclass
import re
from typing import Any

import httpx

from app.core.config import settings

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather interpretation codes -> spoken description
_WEATHER_CODES: dict[int, str] = {
    0: "clear skies",
    1: "mostly clear skies",
    2: "partly cloudy",
    3: "overcast",
    45: "foggy",
    48: "icy fog",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    66: "freezing drizzle",
    67: "freezing rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    77: "snow grains",
    80: "light showers",
    81: "showers",
    82: "heavy showers",
    85: "snow showers",
    86: "heavy snow showers",
    95: "a thunderstorm",
    96: "a thunderstorm with hail",
    99: "a severe thunderstorm with hail",
}


def _describe_conditions(code: int) -> str:
    full = "sunny" if code == 0 else f"with { _WEATHER_CODES.get(code, 'mixed conditions')}"
    return full if code != 0 else full


def _rain_like(code: int) -> bool:
    return code in {51, 53, 55, 61, 63, 65, 66, 80, 81, 82, 95, 96, 99} or code in {71, 73, 75, 85, 86}


def _clean_unit(value: float) -> str:
    if abs(value - round(value)) < 0.05:
        return str(int(round(value)))
    return str(round(value, 1))


@dataclass
class WeatherReport:
    temperature_c: float
    apparent_c: float
    humidity_pct: int
    wind_kmh: float
    conditions: str
    is_raining: bool
    rain_probability_today: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def fetch_weather(lat: float, lon: float) -> dict[str, Any]:
    """Fetch current conditions + daily rain probability from Open-Meteo."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,weather_code,wind_speed_10m",
        "daily": "precipitation_probability_max",
        "timezone": "auto",
        "forecast_days": 1,
    }
    async with httpx.AsyncClient(timeout=8.0) as client:
        response = await client.get(OPEN_METEO_URL, params=params)
        response.raise_for_status()
        return response.json()


def parse_weather_report(data: dict[str, Any]) -> WeatherReport:
    current = data.get("current", {})

    def _f(key: str, default: float = 0.0) -> float:
        value = current.get(key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _num(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    daily = data.get("daily", {})
    probabilities = daily.get("precipitation_probability_max") or []
    rain_probability = int(round(_num(probabilities[0]))) if probabilities else None

    code = int(_f("weather_code"))
    conditions = _WEATHER_CODES.get(code, "mixed conditions")
    return WeatherReport(
        temperature_c=_f("temperature_2m"),
        apparent_c=_f("apparent_temperature"),
        humidity_pct=int(round(_f("relative_humidity_2m"))),
        wind_kmh=_f("wind_speed_10m"),
        conditions=conditions,
        is_raining=_rain_like(code) or _f("precipitation") > 0.1,
        rain_probability_today=rain_probability,
    )


def format_weather_answer(report: WeatherReport, location_label: str | None = None) -> str:
    temp = _clean_unit(report.temperature_c)
    feels = _clean_unit(report.apparent_c)
    heat = report.temperature_c >= 26
    cold = report.temperature_c <= 5

    if heat:
        temp_phrase = f"a warm {temp} degrees"
    elif cold:
        temp_phrase = f"a cold {temp} degrees"
    else:
        temp_phrase = f"{temp} degrees"

    location_phrase = f" in {location_label}" if location_label else ""
    humidity_phrase = f" and {report.humidity_pct} percent humidity" if report.humidity_pct > 0 else ""
    wind_phrase = f", wind speed {_clean_unit(report.wind_kmh)} kilometers per hour" if report.wind_kmh > 0 else ""

    if report.is_raining and report.rain_probability_today is not None and report.rain_probability_today >= 50:
        return (
            f"It is raining{location_phrase}, {report.conditions}, {temp_phrase}. "
            f"There is a {report.rain_probability_today} percent chance of rain today, so consider carrying an umbrella."
        )

    if report.rain_probability_today is not None and report.rain_probability_today >= 40:
        return (
            f"Currently {report.conditions}{location_phrase} at {temp_phrase}"
            f"{humidity_phrase}{wind_phrase}. "
            f"There is a {report.rain_probability_today} percent chance of rain today, so you may need an umbrella."
        )

    return (
        f"Currently {report.conditions}{location_phrase} at {temp_phrase}"
        f"{humidity_phrase}{wind_phrase}."
    )


def format_rain_answer(report: WeatherReport, location_label: str | None = None) -> str:
    location_phrase = f" in {location_label}" if location_label else ""
    if report.is_raining:
        return f"Yes, it is raining{location_phrase} right now. {report.conditions.capitalize()}."
    if report.rain_probability_today is None:
        return f"I do not have a rain forecast for your location{location_phrase}."
    if report.rain_probability_today >= 40:
        return (
            f"Yes, there is a {report.rain_probability_today} percent chance of rain"
            f"{location_phrase} today. Carry an umbrella."
        )
    return f"No significant rain is expected{location_phrase} today. A {report.rain_probability_today} percent chance."


def resolve_location_defaults() -> tuple[float, float, str | None]:
    """Coordinates used when the client cannot provide a location."""
    lat = float(settings.default_weather_lat)
    lon = float(settings.default_weather_lon)
    label = (settings.default_weather_city or "").strip() or None
    return lat, lon, label


def is_rain_question(question: str) -> bool:
    return re.search(r"\b(rain|raining|precipitat)\b", question, re.IGNORECASE) is not None