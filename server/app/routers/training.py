from __future__ import annotations

from fastapi import APIRouter, Request

from ..core.responses import fail, ok
from ..services.training_service import create_evaluation_job, create_training_job, evaluation_by_id, evaluation_result_file_response, import_evaluation_result_file, list_evaluations, list_loras, update_evaluation, update_evaluation_result, update_lora

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


@router.get("/evaluations/{evaluation_id}")
def api_evaluation(evaluation_id: str):
    try:
        return ok({"evaluation": evaluation_by_id(evaluation_id)})
    except RuntimeError as error:
        return fail(str(error), 404)


@router.post("/evaluations")
async def api_create_evaluation(request: Request):
    try:
        return ok(create_evaluation_job(await request.json()))
    except RuntimeError as error:
        return fail(str(error), 400)


@router.put("/evaluations/{evaluation_id}")
async def api_update_evaluation(evaluation_id: str, request: Request):
    try:
        return ok({"evaluation": update_evaluation(evaluation_id, await request.json())})
    except RuntimeError as error:
        return fail(str(error), 404)


@router.put("/evaluations/{evaluation_id}/results/{result_id}")
async def api_update_evaluation_result(evaluation_id: str, result_id: str, request: Request):
    try:
        return ok({"evaluation": update_evaluation_result(evaluation_id, result_id, await request.json())})
    except RuntimeError as error:
        return fail(str(error), 404)


@router.post("/evaluations/{evaluation_id}/results/{result_id}/import-file")
async def api_import_evaluation_result_file(evaluation_id: str, result_id: str, request: Request):
    try:
        filename = request.query_params.get("filename") or "result.png"
        return ok({"evaluation": import_evaluation_result_file(evaluation_id, result_id, filename, await request.body())})
    except RuntimeError as error:
        return fail(str(error), 400)


@router.get("/evaluations/{evaluation_id}/results/{result_id}/file")
def api_evaluation_result_file(evaluation_id: str, result_id: str):
    try:
        return evaluation_result_file_response(evaluation_id, result_id)
    except RuntimeError as error:
        return fail(str(error), 404)
