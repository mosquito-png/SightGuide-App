from fastapi import Request
from fastapi.responses import JSONResponse


class ApplicationError(Exception):
    status_code = 400
    code = "application_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class AuthenticationError(ApplicationError):
    status_code = 401
    code = "authentication_error"


class AuthorizationError(ApplicationError):
    status_code = 403
    code = "authorization_error"


class UpstreamServiceError(ApplicationError):
    status_code = 502
    code = "upstream_service_error"


async def application_error_handler(_: Request, error: ApplicationError) -> JSONResponse:
    return JSONResponse(status_code=error.status_code, content={"error": {"code": error.code, "message": error.message}})
