from __future__ import annotations

from fastapi import APIRouter, Request

from ..core.responses import fail, ok
from ..services.training_service import create_evaluation_job, create_training_job, list_evaluations, list_loras, update_lora

router = APIRouter(prefix="/api", tags=["training"])


@router.get("/loras")
def api_loras():
    return ok({"loras": list_loras()})


@router.put("/loras/{lora_id}")
async def api_update_lora(lora_id: str, request: Request):
    try:
        return ok({"lora": update_lora(lora_id, await request.json())})
    except RuntimeError as error:
        return fail(str(error), 404)


@router.post("/training/jobs")
async def api_training_jobs(request: Request):
    try:
        return ok(create_training_job(await request.json()))
    except RuntimeError as error:
        return fail(str(error), 400)


@router.get("/evaluations")
def api_evaluations():
    return ok({"evaluations": list_evaluations()})


@router.post("/evaluations")
async def api_create_evaluation(request: Request):
    try:
        return ok(create_evaluation_job(await request.json()))
    except RuntimeError as error:
        return fail(str(error), 400)
