from __future__ import annotations

from fastapi import APIRouter, Request

from ..core.responses import fail, ok
from ..services.dataset_service import create_dataset, dataset_image_file_response, import_dataset_image, list_dataset_images, list_datasets, mark_dataset_images_by_filter, screen_dataset_images, update_dataset_image
from ..services.task_service import start_annotation

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


@router.get("")
def api_datasets():
    return ok({"datasets": list_datasets()})


@router.post("")
async def api_create_dataset(request: Request):
    return ok({"dataset": create_dataset(await request.json())})


@router.get("/{dataset_id}/images")
def api_dataset_images(dataset_id: str):
    return ok({"images": list_dataset_images(dataset_id)})


@router.get("/{dataset_id}/images/{image_id}/file")
def api_dataset_image_file(dataset_id: str, image_id: str):
    try:
        return dataset_image_file_response(dataset_id, image_id)
    except RuntimeError as error:
        return fail(str(error), 404)


@router.put("/{dataset_id}/images/{image_id}")
async def api_update_dataset_image(dataset_id: str, image_id: str, request: Request):
    try:
        return ok(update_dataset_image(dataset_id, image_id, await request.json()))
    except RuntimeError as error:
        return fail(str(error), 404)


@router.post("/{dataset_id}/images/screen")
async def api_screen_dataset_images(dataset_id: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        return ok(screen_dataset_images(dataset_id, body))
    except RuntimeError as error:
        return fail(str(error), 400)


@router.post("/{dataset_id}/images/import-file")
async def api_import_dataset_image(dataset_id: str, request: Request):
    try:
        filename = request.query_params.get("filename") or "image.jpg"
        return ok(import_dataset_image(dataset_id, filename, await request.body()))
    except RuntimeError as error:
        return fail(str(error), 400)


@router.post("/{dataset_id}/images/mark-by-filter")
async def api_mark_dataset_images_by_filter(dataset_id: str, request: Request):
    try:
        return ok(mark_dataset_images_by_filter(dataset_id, await request.json()))
    except RuntimeError as error:
        return fail(str(error), 400)


@router.post("/{dataset_id}/images/annotate")
async def api_annotate_dataset_images(dataset_id: str, request: Request):
    try:
        return ok({"task": start_annotation(dataset_id, await request.json())})
    except RuntimeError as error:
        return fail(str(error), 400)
