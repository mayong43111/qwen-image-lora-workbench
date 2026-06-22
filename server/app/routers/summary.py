from __future__ import annotations

from fastapi import APIRouter

from ..core.config import DATASETS_PATH, IMAGES_PATH, LORAS_PATH
from ..core.responses import ok
from ..core.storage import read_json
from ..services.dataset_service import summarize_datasets
from ..services.task_service import list_tasks

router = APIRouter(prefix="/api", tags=["summary"])


@router.get("/summary")
def api_summary():
    datasets = read_json(DATASETS_PATH, [])
    images = read_json(IMAGES_PATH, [])
    loras = read_json(LORAS_PATH, [])
    tasks = list_tasks()
    summarized = summarize_datasets(datasets, images)
    return ok({"datasets": len(summarized), "loras": len(loras), "runningTasks": len([task for task in tasks if task.get("status") == "运行中"])})
