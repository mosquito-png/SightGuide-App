import os

from fastapi import APIRouter, Depends

from app.core.config import settings
from app.core.security import authenticate
from app.schemas.guidance import (
    GuidanceRequest,
    GuidanceResponse,
    MapsConfigResponse,
    NavigationRouteRequest,
    NavigationRouteResponse,
    OCRReadTextRequest,
    OCRReadTextResponse,
    PlaceSearchRequest,
    PlaceSearchResult,
    VisionDetectionRequest,
    VisionDetectionResponse,
    VoiceAssistantQueryRequest,
    VoiceAssistantQueryResponse,
)
from app.services.guidance import (
    calculate_walking_route,
    describe_scene,
    detect_obstacles_and_objects,
    handle_voice_assistant_query,
    read_image_text,
    search_destination_place,
)

router = APIRouter(prefix="/guidance", tags=["guidance"])


@router.get("/maps_config", response_model=MapsConfigResponse)
async def maps_config() -> MapsConfigResponse:
    """Return whether Google Maps is configured and the client-side API key.

    The key comes from ``GOOGLE_MAPS_API_KEY`` in the backend environment file;
    it is never hard-coded and is provided to the browser only so the Google
    Maps JavaScript API can be rendered client-side. Never log this value.
    """
    key = (settings.google_maps_api_key or os.getenv("GOOGLE_MAPS_API_KEY", "").strip())
    map_id = (settings.google_maps_map_id or os.getenv("GOOGLE_MAPS_MAP_ID", "").strip()) or None
    return MapsConfigResponse(configured=bool(key), api_key=key or None, map_id=map_id)


@router.post("/describe", response_model=GuidanceResponse)
async def describe(request: GuidanceRequest, _: str = Depends(authenticate)) -> GuidanceResponse:
    return await describe_scene(request.scene)


@router.post("/detect", response_model=VisionDetectionResponse)
async def detect(
    request: VisionDetectionRequest,
    _: str = Depends(authenticate),
) -> VisionDetectionResponse:
    return await detect_obstacles_and_objects(
        image_base64=request.image_base64,
        mode=request.mode,
        prompt_override=request.prompt_override,
    )


@router.post("/read_text", response_model=OCRReadTextResponse)
async def read_text(
    request: OCRReadTextRequest,
    _: str = Depends(authenticate),
) -> OCRReadTextResponse:
    return await read_image_text(
        image_base64=request.image_base64,
        focus_area=request.focus_area,
        prompt_override=request.prompt_override,
    )


@router.post("/ask", response_model=VoiceAssistantQueryResponse)
async def ask(
    request: VoiceAssistantQueryRequest,
    _: str = Depends(authenticate),
) -> VoiceAssistantQueryResponse:
    return await handle_voice_assistant_query(
        question=request.question,
        image_base64=request.image_base64,
        context=request.context,
    )


@router.post("/route", response_model=NavigationRouteResponse)
async def get_route(
    request: NavigationRouteRequest,
    _: str = Depends(authenticate),
) -> NavigationRouteResponse:
    return await calculate_walking_route(
        origin_lat=request.origin_lat,
        origin_lng=request.origin_lng,
        destination=request.destination,
        destination_lat=request.destination_lat,
        destination_lng=request.destination_lng,
    )


@router.post("/search_place", response_model=PlaceSearchResult)
async def search_place(
    request: PlaceSearchRequest,
    _: str = Depends(authenticate),
) -> PlaceSearchResult:
    return await search_destination_place(
        origin_lat=request.origin_lat,
        origin_lng=request.origin_lng,
        query=request.query,
    )




