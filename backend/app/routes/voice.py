from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import json

from app.assistant import command
from app.schemas.voice import ConversationTurn, VoiceCommandRequest, VoiceCommandResponse

router = APIRouter(prefix="/voice", tags=["voice"])


@router.post("/command", response_model=VoiceCommandResponse)
async def voice_command(request: VoiceCommandRequest) -> VoiceCommandResponse:
    """Classify a spoken transcript and produce the assistant's spoken reply.

    The client performs wake-word listening, STT and TTS in the browser. This
    endpoint is the canonical intent router: device-time/date, real weather,
    vision (camera + YOLO) and LLM answers are produced here, and device
    actions (call / message / reminder / sos) come back as directives for the
    browser to execute.
    """
    return await command.handle_voice_command(
        text=request.text,
        context=[(turn.role, turn.text) for turn in request.context],
        lat=request.lat,
        lon=request.lon,
        location_label=request.location_label,
        image_base64=request.image_base64,
    )


@router.websocket("/ws")
async def voice_websocket(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time bidirectional voice assistant communication."""
    await websocket.accept()
    await websocket.send_json({"type": "state", "state": "connected"})

    try:
        while True:
            raw_data = await websocket.receive_text()
            try:
                msg = json.loads(raw_data)
            except Exception:
                continue

            msg_type = msg.get("type")
            if msg_type == "wake_word":
                await websocket.send_json({"type": "state", "state": "listening"})
            elif msg_type == "speech_start":
                await websocket.send_json({"type": "state", "state": "listening"})
            elif msg_type == "stop":
                await websocket.send_json({"type": "state", "state": "idle"})
            elif msg_type == "speech":
                text = str(msg.get("text", "")).strip()
                if not text:
                    continue
                context_raw = msg.get("context") or []
                context_tuples = [(c.get("role", "user"), c.get("text", "")) for c in context_raw if isinstance(c, dict)]
                res = await command.handle_voice_command(
                    text=text,
                    context=context_tuples if context_tuples else None,
                    lat=msg.get("lat"),
                    lon=msg.get("lon"),
                    location_label=msg.get("location_label"),
                    image_base64=msg.get("image_base64"),
                )
                await websocket.send_json({
                    "type": "response",
                    "message": res.text,
                    "priority": res.priority,
                    "action": res.action,
                    "navigation_destination": res.navigation_destination,
                    "detected_items": res.detected_items,
                    "directives": [d.model_dump() for d in res.directives],
                    "needs_frame": res.needs_frame,
                    "extracted_text": res.extracted_text,
                })
    except WebSocketDisconnect:
        pass
    except Exception:
        pass