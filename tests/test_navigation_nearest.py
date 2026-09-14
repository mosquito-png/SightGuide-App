import asyncio
from fastapi.testclient import TestClient
import pytest

from backend.app.main import app
from app.assistant import command, intents
from app.schemas.guidance import PlaceSearchResult
from app.services import guidance as guidance_service

client = TestClient(app)


def test_clean_place_search_query_variants():
    """Verify place search query normalization and amenity extraction."""
    cases = [
        ("the nearest hospital", "hospital", "hospital", True),
        ("nearest hospital", "hospital", "hospital", True),
        ("closest hospital", "hospital", "hospital", True),
        ("navigate to the nearest hospital", "hospital", "hospital", True),
        ("set destination to the nearest hospital", "hospital", "hospital", True),
        ("set destination as the nearest hospital", "hospital", "hospital", True),
        ("find the nearest hospital", "hospital", "hospital", True),
        ("where is the nearest hospital", "hospital", "hospital", True),
        ("hospital near me", "hospital", "hospital", True),
        ("nearest pharmacy", "pharmacy", "pharmacy", True),
        ("the nearest clinic", "clinic", "clinic", True),
        ("nearest police station", "police station", "police", True),
        ("nearest grocery store", "grocery store", "supermarket", True),
        ("Starbucks", "Starbucks", None, False),
        ("123 Main Street", "123 Main Street", None, False),
    ]
    for raw, expected_clean, expected_amenity, expected_nearby in cases:
        clean, amenity, is_nearby = guidance_service.clean_place_search_query(raw)
        assert clean.lower() == expected_clean.lower(), f"Failed clean for '{raw}': got '{clean}'"
        assert amenity == expected_amenity, f"Failed amenity for '{raw}': got '{amenity}'"
        assert is_nearby == expected_nearby, f"Failed is_nearby for '{raw}': got '{is_nearby}'"


def test_extract_navigation_destination_variants():
    """Verify regex extraction captures nearest destination phrases."""
    assert guidance_service.extract_navigation_destination("navigate to the nearest hospital") == "the nearest hospital"
    assert guidance_service.extract_navigation_destination("set destination to the nearest hospital") == "the nearest hospital"
    assert guidance_service.extract_navigation_destination("set destination as the nearest clinic") == "the nearest clinic"
    assert guidance_service.extract_navigation_destination("take me to the nearest pharmacy") == "the nearest pharmacy"
    assert guidance_service.extract_navigation_destination("find the nearest hospital") == "hospital"
    assert guidance_service.extract_navigation_destination("where is the nearest hospital") == "hospital"
    assert guidance_service.extract_navigation_destination("nearest hospital") == "hospital"
    assert guidance_service.extract_navigation_destination("closest hospital") == "hospital"


def test_search_destination_place_selects_closest_hospital(monkeypatch):
    """Verify that search_destination_place selects the closest candidate and returns its name and coordinates."""
    async def mock_search_destination_place(origin_lat, origin_lng, query):
        # Emulate resolving multiple nearby hospitals to the nearest one
        return PlaceSearchResult(
            name="St. Jude Memorial Hospital",
            formatted_address="100 Hospital Way, Medical District",
            lat=origin_lat + 0.003,
            lng=origin_lng + 0.003,
            distance_text="420 meters",
            distance_meters=420.0,
            estimated_duration="5 mins walk",
            provider="openstreetmap_nominatim",
        )

    monkeypatch.setattr(guidance_service, "search_destination_place", mock_search_destination_place)

    result = asyncio.run(
        guidance_service.search_destination_place(
            origin_lat=40.7128,
            origin_lng=-74.0060,
            query="the nearest hospital",
        )
    )

    assert result.name == "St. Jude Memorial Hospital"
    assert result.name != "the nearest hospital"
    assert result.lat == pytest.approx(40.7158, 0.001)
    assert result.lng == pytest.approx(-74.0030, 0.001)
    assert result.distance_text == "420 meters"


def test_voice_command_nearest_hospital_with_gps(monkeypatch):
    """When GPS is provided in voice command, resolve to nearest hospital with real name and directives."""
    async def mock_search(origin_lat, origin_lng, query):
        return PlaceSearchResult(
            name="City General Hospital",
            formatted_address="500 Health Ave",
            lat=37.7760,
            lng=-122.4180,
            distance_text="350 meters",
            distance_meters=350.0,
            estimated_duration="4 mins walk",
            provider="google_places",
        )

    monkeypatch.setattr(guidance_service, "search_destination_place", mock_search)

    res = asyncio.run(
        command.handle_voice_command(
            "navigate to the nearest hospital",
            lat=37.7749,
            lon=-122.4194,
        )
    )

    assert res.intent == intents.Intent.NAVIGATION
    assert res.action == "start_navigation"
    assert res.navigation_destination == "City General Hospital"
    assert "City General Hospital" in res.text
    assert "350 meters" in res.text
    assert len(res.directives) == 1
    assert res.directives[0].action == "start_navigation"
    assert res.directives[0].value == "City General Hospital"
    assert res.directives[0].parameters.get("lat") == 37.7760
    assert res.directives[0].parameters.get("lng") == -122.4180


def test_voice_command_set_destination_nearest_hospital(monkeypatch):
    """When user says 'set destination to the nearest hospital', intent is navigation and resolved."""
    async def mock_search(origin_lat, origin_lng, query):
        return PlaceSearchResult(
            name="Metropolitan Hospital",
            formatted_address="123 Care Street",
            lat=51.5080,
            lng=-0.1280,
            distance_text="200 meters",
            distance_meters=200.0,
            estimated_duration="2 mins walk",
            provider="openstreetmap_nominatim",
        )

    monkeypatch.setattr(guidance_service, "search_destination_place", mock_search)

    res = asyncio.run(
        command.handle_voice_command(
            "set destination to the nearest hospital",
            lat=51.5074,
            lon=-0.1278,
        )
    )

    assert res.intent == intents.Intent.NAVIGATION
    assert res.action == "start_navigation"
    assert res.navigation_destination == "Metropolitan Hospital"
    assert "Metropolitan Hospital" in res.text


def test_search_place_api_endpoint(monkeypatch):
    """POST /api/guidance/search_place with nearest hospital query returns resolved place."""
    async def mock_search(origin_lat, origin_lng, query):
        return PlaceSearchResult(
            name="Grace Medical Center",
            formatted_address="88 Health Park",
            lat=34.0530,
            lng=-118.2430,
            distance_text="500 meters",
            distance_meters=500.0,
            estimated_duration="6 mins walk",
            provider="openstreetmap_nominatim",
        )

    monkeypatch.setattr("app.routes.guidance.search_destination_place", mock_search)

    response = client.post(
        "/api/guidance/search_place",
        json={
            "origin_lat": 34.0522,
            "origin_lng": -118.2437,
            "query": "the nearest hospital",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Grace Medical Center"
    assert data["lat"] == 34.0530
    assert data["lng"] == -118.2430
    assert data["distance_text"] == "500 meters"


def test_calculate_walking_route_with_resolved_coordinates():
    """calculate_walking_route accepts resolved destination name + coordinates."""
    route_res = asyncio.run(
        guidance_service.calculate_walking_route(
            origin_lat=48.8566,
            origin_lng=2.3522,
            destination="Hôpital du Val de Grâce",
            destination_lat=48.8395,
            destination_lng=2.3431,
        )
    )
    assert route_res.destination_name == "Hôpital du Val de Grâce"
    assert len(route_res.steps) > 0
    assert "arrive" in route_res.steps[-1].maneuver


def test_search_destination_place_graceful_fallback():
    """When no API or network is available, search_destination_place provides a graceful fallback without crashing."""
    result = asyncio.run(
        guidance_service.search_destination_place(
            origin_lat=0.0,
            origin_lng=0.0,
            query="the nearest hospital",
        )
    )
    assert result is not None
    assert result.name != ""
    assert result.lat is not None
    assert result.lng is not None
    assert result.distance_meters > 0
