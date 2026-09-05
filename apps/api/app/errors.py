import uuid

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def _payload(request: Request, code: str, message: str, fields: dict | None = None) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": getattr(request.state, "request_id", str(uuid.uuid4())),
            "fields": fields,
        }
    }


async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
    codes = {
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        429: "rate_limited",
    }
    return JSONResponse(
        _payload(request, codes.get(exc.status_code, "request_error"), str(exc.detail)),
        status_code=exc.status_code,
    )


async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    fields = {".".join(map(str, item["loc"][1:])): item["msg"] for item in exc.errors()}
    return JSONResponse(
        _payload(request, "validation_error", "Проверьте заполненные поля", fields), status_code=422
    )
