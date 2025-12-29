from __future__ import annotations

import secrets
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from app.api.router import router as api_router
from app.ui.router import router as ui_router


def create_app() -> FastAPI:
    app = FastAPI(title="Новогодняя страховая компания (demo)")

    # Session (signed cookie). No DB.
    app.add_middleware(SessionMiddleware, secret_key=secrets.token_urlsafe(32), same_site="lax")

    # RequestId middleware
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next: Callable):  # type: ignore[override]
        req_id = request.headers.get("X-Request-Id")
        if not req_id:
            req_id = secrets.token_hex(16)
        request.state.request_id = req_id
        response = await call_next(request)
        response.headers["X-Request-Id"] = req_id
        return response

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):  # noqa: ARG001
        return JSONResponse(
            status_code=500,
            content={
                "title": "Internal error",
                "detail": "Внутренняя ошибка. Эльфы уже бегут чинить.",
                "requestId": getattr(request.state, "request_id", None),
            },
        )

    app.mount("/static", StaticFiles(directory="app/static"), name="static")
    app.include_router(ui_router)
    app.include_router(api_router)

    return app


app = create_app()
