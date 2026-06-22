from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ANNOTATION_SETTINGS_PATH, DATA_DIR, DATA_ROOT, DATASETS_PATH, DEFAULT_ANNOTATION_SETTINGS, DEFAULT_PROMPT, EVALUATIONS_PATH, EVALUATION_RUNS_DIR, IMAGES_PATH, LORAS_PATH, PROMPT_PATH, TASKS_PATH, TRAINING_RUNS_DIR, VIDEOS_DIR, VIDEOS_PATH

file_lock = threading.Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def ensure_data() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_ROOT / "datasets").mkdir(parents=True, exist_ok=True)
    TRAINING_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    EVALUATION_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    if not DATASETS_PATH.exists():
        write_json(DATASETS_PATH, [])
    if not VIDEOS_PATH.exists():
        write_json(VIDEOS_PATH, [])
    if not IMAGES_PATH.exists():
        write_json(IMAGES_PATH, [])
    if not TASKS_PATH.exists():
        write_json(TASKS_PATH, [])
    if not LORAS_PATH.exists():
        write_json(LORAS_PATH, [])
    if not EVALUATIONS_PATH.exists():
        write_json(EVALUATIONS_PATH, [])
    if not PROMPT_PATH.exists():
        PROMPT_PATH.write_text(DEFAULT_PROMPT, encoding="utf-8")
    if not ANNOTATION_SETTINGS_PATH.exists():
        write_json(ANNOTATION_SETTINGS_PATH, DEFAULT_ANNOTATION_SETTINGS)


def read_json(file_path: Path, fallback: Any) -> Any:
    try:
        with file_lock:
            return json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def write_json(file_path: Path, value: Any) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2)
    with file_lock:
        file_path.write_text(text, encoding="utf-8")


def safe_id(value: Any, prefix: str) -> str:
    value = re.sub(r"[^a-z0-9_-]+", "_", str(value or "").strip().lower())
    value = re.sub(r"^[_-]+|[_-]+$", "", value)
    if not value or not re.search(r"[a-z0-9]", value):
        return f"{prefix}_{int(time.time() * 1000)}"
    return value


def safe_file_name(value: Any) -> str:
    parsed = Path(str(value or "video.mp4"))
    name = re.sub(r"[^a-zA-Z0-9._-]+", "_", parsed.stem).strip("_") or "video"
    ext = re.sub(r"[^a-zA-Z0-9.]+", "", parsed.suffix) or ".mp4"
    return f"{name}_{int(time.time() * 1000)}{ext}"


def unique_id(value: Any, prefix: str, rows: list[dict[str, Any]]) -> str:
    base = safe_id(value, prefix)
    ids = {row.get("id") for row in rows}
    return base if base not in ids else f"{base}_{int(time.time() * 1000)}"
