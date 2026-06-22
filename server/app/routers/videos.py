from __future__ import annotations

from fastapi import APIRouter, Query, Request

from ..core.responses import fail, ok
from ..services.video_service import create_video_from_local_path, import_uploaded_video, list_magnet_files, list_videos, rename_video, reprobe_video, start_video_download, video_file_response

router = APIRouter(prefix="/api/videos", tags=["videos"])


@router.get("")
def api_videos():
    return ok({"videos": list_videos()})


@router.get("/{video_id}/file")
def api_video_file(video_id: str):
    return video_file_response(video_id)


@router.post("/import-file")
async def api_import_file(request: Request, filename: str = Query("video.mp4"), title: str | None = Query(None)):
    return ok({"video": await import_uploaded_video(request, filename, title)})


@router.post("/import")
async def api_import_video(request: Request):
    return ok({"video": create_video_from_local_path(await request.json())})


@router.post("/download")
async def api_download_video(request: Request):
    return ok({"task": start_video_download(await request.json())})


@router.post("/magnet/files")
async def api_magnet_files(request: Request):
    body = await request.json()
    try:
        return ok({"files": list_magnet_files(body.get("url"))})
    except RuntimeError as error:
        return fail(str(error))


@router.post("/{video_id}/probe")
def api_probe_video(video_id: str):
    return ok({"video": reprobe_video(video_id)})


@router.put("/{video_id}")
async def api_update_video(video_id: str, request: Request):
    body = await request.json()
    return ok({"video": rename_video(video_id, body.get("title"))})
