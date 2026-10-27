import uuid

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message


async def api_error_handler(request: Request, exc: ApiError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message, "requestId": str(uuid.uuid4())},
    )


def not_implemented():
    return ApiError(501, "NOT_IMPLEMENTED", "This endpoint is not implemented yet")
