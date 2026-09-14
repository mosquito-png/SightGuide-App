from app.schemas.guidance import GuidanceResponse


def validate_result(result: GuidanceResponse) -> GuidanceResponse:
    if not result.message.strip():
        raise ValueError("Tool returned an empty response")
    return result
