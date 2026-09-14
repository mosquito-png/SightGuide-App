from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def test_health_check() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_guidance_describes_scene(monkeypatch) -> None:
    async def fake_describe(_: str):
        from backend.app.schemas.guidance import GuidanceResponse

        return GuidanceResponse(message="A laptop is on a desk.", priority="normal")

    monkeypatch.setattr("app.routes.guidance.describe_scene", fake_describe)
    response = client.post("/api/guidance/describe", json={"scene": "three steps"})
    assert response.status_code == 200
    assert response.json() == {"message": "A laptop is on a desk.", "priority": "normal"}


def test_guidance_rejects_empty_scene() -> None:
    response = client.post("/api/guidance/describe", json={"scene": ""})
    assert response.status_code == 422


def test_guidance_detects_obstacles(monkeypatch) -> None:
    async def fake_detect(*args, **kwargs):
        from backend.app.schemas.guidance import DetectedObstacle, VisionDetectionResponse


        return VisionDetectionResponse(
            summary="A person is approaching at 12 o'clock, 2 meters away.",
            priority="warning",
            obstacles=[
                DetectedObstacle(
                    label="person",
                    location_clock="12 o'clock",
                    distance="2 meters",
                    hazard_level="medium",
                )
            ],
        )

    monkeypatch.setattr("app.routes.guidance.detect_obstacles_and_objects", fake_detect)
    response = client.post(
        "/api/guidance/detect",
        json={"image_base64": "data:image/jpeg;base64,fakeimagebytes123456789"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["priority"] == "warning"
    assert len(data["obstacles"]) == 1
    assert data["obstacles"][0]["label"] == "person"
    assert "person is approaching" in data["summary"]


def test_guidance_detect_rejects_empty_image() -> None:
    response = client.post("/api/guidance/detect", json={"image_base64": ""})
    assert response.status_code == 422


def test_guidance_ask_voice_assistant(monkeypatch) -> None:
    async def fake_ask(*args, **kwargs):
        from backend.app.schemas.guidance import VoiceAssistantQueryResponse

        return VoiceAssistantQueryResponse(
            answer="You are holding a bottle of water.",
            action="speak",
            priority="normal",
        )

    monkeypatch.setattr("app.routes.guidance.handle_voice_assistant_query", fake_ask)
    response = client.post(
        "/api/guidance/ask",
        json={"question": "What is in my hand?", "image_base64": "data:image/jpeg;base64,sample"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == "You are holding a bottle of water."
    assert data["action"] == "speak"


def test_guidance_calculates_walking_route(monkeypatch) -> None:
    async def fake_route(*args, **kwargs):
        from backend.app.schemas.guidance import NavigationRouteResponse, NavigationStep

        return NavigationRouteResponse(
            destination_name="Starbucks",
            total_distance="300 m",
            total_duration="4 mins",
            summary="Walk along Main St",
            steps=[
                NavigationStep(
                    instruction="Head north on Main St",
                    distance_text="300 m",
                    distance_meters=300.0,
                    duration_text="4 mins",
                    maneuver="straight",
                )
            ],
            provider="simulated",
        )

    monkeypatch.setattr("app.routes.guidance.calculate_walking_route", fake_route)
    response = client.post(
        "/api/guidance/route",
        json={"origin_lat": 37.7749, "origin_lng": -122.4194, "destination": "Starbucks"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["destination_name"] == "Starbucks"
    assert len(data["steps"]) == 1
    assert "Main St" in data["steps"][0]["instruction"]


def test_guidance_searches_destination_place(monkeypatch) -> None:
    async def fake_search(*args, **kwargs):
        from backend.app.schemas.guidance import PlaceSearchResult

        return PlaceSearchResult(
            name="Starbucks Coffee",
            formatted_address="123 Market St, San Francisco, CA",
            lat=37.7750,
            lng=-122.4180,
            distance_text="350 meters",
            distance_meters=350.0,
            estimated_duration="4 mins walk",
            provider="google_places",
        )

    monkeypatch.setattr("app.routes.guidance.search_destination_place", fake_search)
    response = client.post(
        "/api/guidance/search_place",
        json={"origin_lat": 37.7749, "origin_lng": -122.4194, "query": "Starbucks"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Starbucks Coffee"
    assert data["distance_text"] == "350 meters"
    assert "123 Market St" in data["formatted_address"]


def test_guidance_reads_text_ocr(monkeypatch) -> None:
    async def fake_read(*args, **kwargs):
        from backend.app.schemas.guidance import OCRReadTextResponse

        return OCRReadTextResponse(
            text="Ibuprofen 200mg. Take 1 tablet every 4 to 6 hours.",
            summary="The bottle is Ibuprofen 200 milligrams. Instructions state to take one tablet every 4 to 6 hours.",
            reading_type="product_label",
            priority="normal",
        )

    monkeypatch.setattr("app.routes.guidance.read_image_text", fake_read)
    response = client.post(
        "/api/guidance/read_text",
        json={"image_base64": "data:image/jpeg;base64,medicineframe12345"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["reading_type"] == "product_label"
    assert "Ibuprofen 200mg" in data["text"]
    assert "Ibuprofen 200 milligrams" in data["summary"]


def test_guidance_read_text_rejects_empty_image() -> None:
    response = client.post("/api/guidance/read_text", json={"image_base64": ""})
    assert response.status_code == 422




