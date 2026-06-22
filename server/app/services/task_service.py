from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from ..core.config import CLASSIFY_SCRIPT, DATA_ROOT, DATASETS_PATH, EXTRACT_SCRIPT, IMAGES_PATH, REPO_ROOT, TASKS_PATH, VIDEOS_PATH
from ..core.processes import resolve_ffmpeg, run_process
from ..core.storage import now_iso, read_json, safe_id, write_json


def task_id() -> str:
    return f"task_{int(time.time() * 1000)}"


def start_thread(target: Any, *args: Any) -> None:
    thread = threading.Thread(target=target, args=args, daemon=True)
    thread.start()


def list_tasks() -> list[dict[str, Any]]:
    return read_json(TASKS_PATH, [])


def create_task(kind: str, target: str, input_value: dict[str, Any] | None = None) -> dict[str, Any]:
    tasks = read_json(TASKS_PATH, [])
    task = {
        "id": task_id(),
        "type": kind,
        "target": target,
        "status": "等待中",
        "progress": 0,
        "input": input_value or {},
        "log": [],
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
    }
    tasks.insert(0, task)
    write_json(TASKS_PATH, tasks)
    return task


def update_task(task_id_value: str, patch: dict[str, Any]) -> None:
    tasks = read_json(TASKS_PATH, [])
    index = next((i for i, task in enumerate(tasks) if task.get("id") == task_id_value), -1)
    if index < 0:
        return
    tasks[index] = {**tasks[index], **patch, "updatedAt": now_iso()}
    write_json(TASKS_PATH, tasks)


def append_task_log(task_id_value: str, text: str, progress: float | None = None) -> None:
    tasks = read_json(TASKS_PATH, [])
    index = next((i for i, task in enumerate(tasks) if task.get("id") == task_id_value), -1)
    if index < 0:
        return
    log = [*(tasks[index].get("log") or []), text]
    patch = {"log": log[-120:], "updatedAt": now_iso()}
    if progress is not None:
        patch["progress"] = progress
    tasks[index] = {**tasks[index], **patch}
    write_json(TASKS_PATH, tasks)


def import_frames(dataset_id: str, source_id: str, source_dir: Path) -> int:
    manifest_path = source_dir / "manifests" / "frames_raw.jsonl"
    rows = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line]
    images = read_json(IMAGES_PATH, [])
    existing = {image.get("id") for image in images}
    for row in rows:
        image_id = safe_id(f"{source_id}_{row.get('timestamp_sec')}", "img")
        if image_id in existing:
            continue
        images.append({
            "id": image_id,
            "datasetId": dataset_id,
            "framePath": row.get("frame_path"),
            "sourceId": source_id,
            "timestampSec": row.get("timestamp_sec"),
            "view": "未知",
            "quality": "未检查",
            "annotation": "未标注",
            "selected": True,
            "captionLocked": False,
            "caption": "",
            "suggestion": "",
            "width": row.get("width"),
            "height": row.get("height"),
        })
    write_json(IMAGES_PATH, images)
    return len(rows)


def import_scores(dataset_id: str, source_id: str, source_dir: Path) -> int:
    manifest_path = source_dir / "manifests" / "frames_scored.jsonl"
    rows = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line]
    images = read_json(IMAGES_PATH, [])
    by_id = {image.get("id"): image for image in images}
    updated = 0
    for row in rows:
        image_id = safe_id(f"{source_id}_{row.get('timestamp_sec')}", "img")
        image = by_id.get(image_id)
        if not image:
            continue
        included = bool(row.get("include_in_training"))
        image.update({
            "quality": "已评分",
            "qualityScore": row.get("quality_score"),
            "qualityLabels": row.get("classification_labels") or [],
            "rejectReason": row.get("reject_reason") or "",
            "suggestion": "基础分类通过，可进入人工 caption。" if included else f"基础分类建议剔除：{row.get('reject_reason') or '质量不足'}",
        })
        updated += 1
    write_json(IMAGES_PATH, images)
    return updated


def extraction_worker(task: dict[str, Any], body: dict[str, Any], source_id: str, source_dir: Path, video: dict[str, Any]) -> None:
    args = [
        str(EXTRACT_SCRIPT),
        "--video", str(video.get("localPath")),
        "--output-dir", str(source_dir),
        "--source-id", source_id,
        "--start-sec", str(body.get("startSec", 0)),
        "--interval-sec", str(body.get("intervalSec", 5)),
        "--overwrite",
    ]
    if body.get("endSec") not in (None, ""):
        args.extend(["--end-sec", str(body.get("endSec"))])
    update_task(task["id"], {"status": "运行中", "progress": 5, "log": [f"python {' '.join(args)}"]})
    ffmpeg_dir = Path(resolve_ffmpeg()).parent
    result = run_process("python", args, cwd=REPO_ROOT, extra_path=[ffmpeg_dir])
    if result["stdout"].strip():
        append_task_log(task["id"], result["stdout"].strip(), 50)
    if result["stderr"].strip():
        append_task_log(task["id"], result["stderr"].strip())
    if result["code"] == 0:
        count = import_frames(str(body["datasetId"]), source_id, source_dir)
        update_task(task["id"], {"status": "完成", "progress": 100, "output": {"importedImages": count}})
    else:
        update_task(task["id"], {"status": "失败", "progress": 100, "error": f"抽帧脚本退出码：{result['code']}"})


def start_extraction(body: dict[str, Any]) -> dict[str, Any]:
    videos = read_json(VIDEOS_PATH, [])
    video = next((item for item in videos if item.get("id") == body.get("videoId")), None)
    if not video:
        raise RuntimeError(f"视频不存在：{body.get('videoId')}")
    if not body.get("datasetId"):
        raise RuntimeError("必须选择目标数据集")
    datasets = read_json(DATASETS_PATH, [])
    if not any(item.get("id") == body.get("datasetId") for item in datasets):
        raise RuntimeError(f"目标数据集不存在：{body.get('datasetId')}")
    if not video.get("localPath") or not Path(str(video.get("localPath"))).is_file():
        raise RuntimeError("视频文件不存在，无法抽帧")
    if not EXTRACT_SCRIPT.is_file():
        raise RuntimeError(f"抽帧脚本不存在：{EXTRACT_SCRIPT}")
    source_id = safe_id(f"{body['datasetId']}_{video['id']}_{int(time.time() * 1000)}", "source")
    source_dir = DATA_ROOT / "datasets" / str(body["datasetId"]) / "sources" / source_id
    source_dir.mkdir(parents=True, exist_ok=True)
    task = create_task("抽帧", f"{video.get('title')} -> {body['datasetId']}", {**body, "sourceId": source_id, "sourceDir": str(source_dir)})
    start_thread(extraction_worker, task, body, source_id, source_dir, video)
    return task


def classification_worker(task: dict[str, Any], body: dict[str, Any]) -> None:
    args = [str(CLASSIFY_SCRIPT), "--source-dir", str(body["sourceDir"]), "--copy-files", "--overwrite"]
    update_task(task["id"], {"status": "运行中", "progress": 10, "log": [f"python {' '.join(args)}"]})
    result = run_process("python", args, cwd=REPO_ROOT)
    if result["stdout"].strip():
        append_task_log(task["id"], result["stdout"].strip(), 70)
    if result["stderr"].strip():
        append_task_log(task["id"], result["stderr"].strip())
    if result["code"] == 0:
        count = import_scores(str(body["datasetId"]), str(body["sourceId"]), Path(str(body["sourceDir"])))
        update_task(task["id"], {"status": "完成", "progress": 100, "output": {"updatedImages": count}})
    else:
        update_task(task["id"], {"status": "失败", "progress": 100, "error": f"分类脚本退出码：{result['code']}"})


def start_classification(body: dict[str, Any]) -> dict[str, Any]:
    if not body.get("datasetId"):
        raise RuntimeError("必须提供 datasetId")
    if not body.get("sourceId"):
        raise RuntimeError("必须提供 sourceId")
    if not body.get("sourceDir"):
        raise RuntimeError("必须提供 sourceDir")
    if not CLASSIFY_SCRIPT.is_file():
        raise RuntimeError(f"分类脚本不存在：{CLASSIFY_SCRIPT}")
    task = create_task("基础分类", f"{body['sourceId']} -> {body['datasetId']}", body)
    start_thread(classification_worker, task, body)
    return task


def annotation_worker(task: dict[str, Any], dataset_id: str, body: dict[str, Any]) -> None:
    from .annotation_service import annotate_dataset_images

    image_count = len(body.get("imageIds") or [])
    update_task(task["id"], {"status": "运行中", "progress": 5, "log": [f"开始智能体标注：{dataset_id}，图片 {image_count or '全部'} 张"]})
    try:
        result = annotate_dataset_images(dataset_id, body)
        failed = result.get("failed") or []
        updated = int(result.get("updated") or 0)
        if failed:
            append_task_log(task["id"], f"标注完成：成功 {updated} 张，失败 {len(failed)} 张", 90)
        else:
            append_task_log(task["id"], f"标注完成：成功 {updated} 张", 90)
        update_task(task["id"], {
            "status": "完成",
            "progress": 100,
            "output": {
                "updated": updated,
                "failed": failed,
                "settings": result.get("settings") or {},
            },
        })
    except Exception as error:
        update_task(task["id"], {"status": "失败", "progress": 100, "error": str(error)})


def start_annotation(dataset_id: str, body: dict[str, Any]) -> dict[str, Any]:
    if not dataset_id:
        raise RuntimeError("必须提供 datasetId")
    datasets = read_json(DATASETS_PATH, [])
    dataset = next((item for item in datasets if item.get("id") == dataset_id), None)
    if not dataset:
        raise RuntimeError(f"数据集不存在：{dataset_id}")
    body = body or {}
    image_ids = body.get("imageIds") or []
    target = f"{dataset.get('name') or dataset_id}"
    if image_ids:
        target = f"{target} ({len(image_ids)} 张)"
    task = create_task("智能体标注", target, {**body, "datasetId": dataset_id})
    start_thread(annotation_worker, task, dataset_id, body)
    return task
