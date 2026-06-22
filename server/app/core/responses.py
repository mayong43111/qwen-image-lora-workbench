from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def ok(data: Any = None, message: str = "success", status_code: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"statusCode": status_code, "message": message, "data": data})


def fail(message: str, status_code: int = 500, data: Any = None) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"statusCode": status_code, "message": message, "data": data})


async def exception_handler(_: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, StarletteHTTPException):
        return fail(str(exc.detail), exc.status_code)
    if isinstance(exc, RequestValidationError):
        return fail("请求参数校验失败", 422, exc.errors())
    return fail(str(exc), 500)
