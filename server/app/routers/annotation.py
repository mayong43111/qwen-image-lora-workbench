from __future__ import annotations

from fastapi import APIRouter, Request

from ..core.config import PROMPT_PATH
from ..core.responses import fail, ok
from ..services.annotation_service import get_annotation_settings, save_annotation_settings

router = APIRouter(tags=["annotation"])


@router.get("/api/annotation-prompt")
def api_annotation_prompt():
    return ok({"prompt": PROMPT_PATH.read_text(encoding="utf-8")})


@router.put("/api/annotation-prompt")
async def api_update_annotation_prompt(request: Request):
    body = await request.json()
    PROMPT_PATH.write_text(str(body.get("prompt") or ""), encoding="utf-8")
    return ok({"ok": True})


@router.get("/api/annotation-settings")
def api_annotation_settings():
    return ok({"settings": get_annotation_settings()})


@router.put("/api/annotation-settings")
async def api_update_annotation_settings(request: Request):
    try:
        return ok({"settings": save_annotation_settings(await request.json())})
    except RuntimeError as error:
        return fail(str(error), 400)
