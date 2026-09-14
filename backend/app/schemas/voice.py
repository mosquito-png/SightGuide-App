from datetime import datetime, timezone

from pydantic import BaseModel, Field


class ConversationTurn(BaseModel):
    """One past turn of the voice conversation, kept for short-term context."""

    role: str = Field(pattern="^(user|assistant)$")
    text: str = Field(min_length=1, max_length=1000)


class DeviceDirective(BaseModel):
    """A device action for the client to execute (phone call, message, reminder...).

    The backend classifies intents and decides *what* to do; the browser owns
    the underlying device APIs (tel:, sms:, notifications, GPS), so directives
    describe the action and the frontend actuates it.
    """

    action: str  # call | message | reminder | sos | start_navigation | ...
    value: str | None = None
    parameters: dict[str, object] = Field(default_factory=dict)


class VoiceCommandRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000, description="Spoken command transcript from the client")
    context: list[ConversationTurn] = Field(
        default_factory=list,
        description="Short-term conversation history for follow-up understanding",
    )
    lat: float | None = Field(default=None, ge=-90.0, le=90.0)
    lon: float | None = Field(default=None, ge=-180.0, le=180.0)
    location_label: str | None = Field(default=None, max_length=120)
    image_base64: str | None = Field(default=None, description="Optional camera frame for vision intents")


class VoiceCommandResponse(BaseModel):
    intent: str  # time | date | weather | call | message | reminder | sos | cancel | scene | obstacle | distance | navigation | general
    text: str = Field(default="", description="Spoken answer for the assistant to say")
    priority: str = "normal"  # normal | warning | urgent
    action: str = "speak"  # speak | start_scan | stop_scan | switch_camera | mute | start_navigation
    directives: list[DeviceDirective] = Field(default_factory=list)
    needs_frame: bool = Field(default=False, description="Client should capture a camera frame and re-send")
    navigation_destination: str | None = None
    detected_items: list[str] = Field(default_factory=list)
    extracted_text: str | None = None
    timestamp: str | None = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())