from __future__ import annotations

from fastapi import APIRouter

from ..core.responses import fail, ok
from ..services.model_service import check_model_asset, model_runtime_status

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("/status")
def api_model_status():
    return ok(model_runtime_status())


@router.get("/checks/{asset_id}")
def api_model_check(asset_id: str):
    try:
        return ok({"check": check_model_asset(asset_id)})
    except RuntimeError as error:
        return fail(str(error), 404)
