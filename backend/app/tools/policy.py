from dataclasses import dataclass
from enum import Enum

from app.core.errors import AuthorizationError


class RiskLevel(str, Enum):
    LOW = "low"
    CONFIRM = "confirm"
    HIGH = "high"


@dataclass(frozen=True)
class ToolPolicy:
    risk: RiskLevel = RiskLevel.LOW
    requires_confirmation: bool = False


class PolicyManager:
    def authorize(self, policy: ToolPolicy, confirmed: bool = False) -> None:
        if policy.requires_confirmation and not confirmed:
            raise AuthorizationError("User confirmation is required for this action")
