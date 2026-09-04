from fastapi import Request
from fastapi.responses import JSONResponse


async def unhandled_exception_handler(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": "An internal server error occurred."})