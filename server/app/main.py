from __future__ import annotations

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from .core.config import DATA_ROOT
from .core.responses import exception_handler
from .core.storage import ensure_data
from .routers import annotation, datasets, models, summary, tasks, training, videos
from .services.task_service import mark_interrupted_tasks_recoverable


def create_app() -> FastAPI:
    app = FastAPI(title="Qwen Image LoRA Workbench Local API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "PUT", "OPTIONS"],
        allow_headers=["content-type"],
    )
    app.add_exception_handler(StarletteHTTPException, exception_handler)
    app.add_exception_handler(RequestValidationError, exception_handler)
    app.add_exception_handler(Exception, exception_handler)
    app.include_router(summary.router)
    app.include_router(datasets.router)
    app.include_router(videos.router)
    app.include_router(tasks.router)
    app.include_router(training.router)
    app.include_router(models.router)
    app.include_router(annotation.router)

    @app.on_event("startup")
    def on_startup() -> None:
        ensure_data()
        mark_interrupted_tasks_recoverable()
        print("Local FastAPI listening on http://127.0.0.1:8787")
        print(f"Data root: {DATA_ROOT}")

    return app


app = create_app()
