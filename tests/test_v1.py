from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def test_v1_health_and_guidance_preserve_contract(monkeypatch) -> None:
    async def fake_describe(_: str):
        from backend.app.schemas.guidance import GuidanceResponse

        return GuidanceResponse(message="A laptop is on a desk.", priority="normal")

    async def fake_detect(*args, **kwargs):
        from backend.app.schemas.guidance import DetectedObstacle, VisionDetectionResponse


        return VisionDetectionResponse(
            summary="Clear walkway ahead.",
            priority="normal",
            obstacles=[],
        )

    monkeypatch.setattr("app.api.v1.guidance.describe_scene", fake_describe)
    monkeypatch.setattr("app.api.v1.guidance.detect_obstacles_and_objects", fake_detect)

    assert client.get("/api/v1/health").json() == {"status": "ok"}
    response = client.post("/api/v1/guidance/describe", json={"scene": "a doorway"})
    assert response.status_code == 200
    assert response.json() == {"message": "A laptop is on a desk.", "priority": "normal"}

    detect_res = client.post(
        "/api/v1/guidance/detect",
        json={"image_base64": "fakeframedata123456789"},
    )
    assert detect_res.status_code == 200
    assert detect_res.json()["summary"] == "Clear walkway ahead."

    async def fake_ask(*args, **kwargs):
        from backend.app.schemas.guidance import VoiceAssistantQueryResponse

        return VoiceAssistantQueryResponse(
            answer="The chair is at 2 o'clock, 1 meter away.",
            action="speak",
            priority="normal",
        )

    monkeypatch.setattr("app.api.v1.guidance.handle_voice_assistant_query", fake_ask)
    ask_res = client.post(
        "/api/v1/guidance/ask",
        json={"question": "Where is the chair?"},
    )
    assert ask_res.status_code == 200
    assert "chair is at 2 o'clock" in ask_res.json()["answer"]

    async def fake_route(*args, **kwargs):
        from backend.app.schemas.guidance import NavigationRouteResponse, NavigationStep

        return NavigationRouteResponse(
            destination_name="Pharmacy",
            total_distance="150 m",
            total_duration="2 mins",
            summary="Walk on 1st St",
            steps=[
                NavigationStep(
                    instruction="Walk 150m on 1st St",
                    distance_text="150 m",
                    distance_meters=150.0,
                    duration_text="2 mins",
                    maneuver="straight",
                )
            ],
            provider="simulated",
        )

    monkeypatch.setattr("app.api.v1.guidance.calculate_walking_route", fake_route)
    route_res = client.post(
        "/api/v1/guidance/route",
        json={"origin_lat": 37.7749, "origin_lng": -122.4194, "destination": "Pharmacy"},
    )
    assert route_res.status_code == 200
    assert route_res.json()["destination_name"] == "Pharmacy"

    async def fake_read_text(*args, **kwargs):
        from backend.app.schemas.guidance import OCRReadTextResponse

        return OCRReadTextResponse(
            text="Store Hours: 9am - 9pm",
            summary="The sign indicates store hours from 9 AM to 9 PM.",
            reading_type="sign",
            priority="normal",
        )

    monkeypatch.setattr("app.api.v1.guidance.read_image_text", fake_read_text)
    read_res = client.post(
        "/api/v1/guidance/read_text",
        json={"image_base64": "fakeframeocrdata123"},
    )
    assert read_res.status_code == 200
    assert "Store Hours" in read_res.json()["text"]



