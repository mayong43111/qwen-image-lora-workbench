from __future__ import annotations

from fastapi import APIRouter, Request

from ..core.responses import fail, ok
from ..services.task_service import list_tasks, start_classification, start_extraction

router = APIRouter(tags=["tasks"])


@router.post("/api/extractions")
async def api_extractions(request: Request):
    try:
        return ok({"task": start_extraction(await request.json())})
    except RuntimeError as error:
        return fail(str(error), 400)


@router.post("/api/classifications")
async def api_classifications(request: Request):
    try:
        return ok({"task": start_classification(await request.json())})
    except RuntimeError as error:
        return fail(str(error), 400)


@router.get("/api/tasks")
def api_tasks():
    return ok({"tasks": list_tasks()})
