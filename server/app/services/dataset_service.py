from __future__ import annotations

from pathlib import Path
from statistics import mean, pstdev
from typing import Any
import re

from fastapi.responses import FileResponse
from PIL import Image

from ..core.config import DATA_ROOT, DATASETS_PATH, IMAGES_PATH
from ..core.storage import now_iso, read_json, unique_id, write_json


REJECT_LABELS = {
    "black_or_near_black",
    "white_or_flash",
    "blurry_motion",
}

LABEL_ALIASES = {
    "black_frame": "black_or_near_black",
    "low_information": "blurry_motion",
}

LABEL_REASONS = {
    "black_or_near_black": "画面整体接近黑屏",
    "white_or_flash": "画面整体接近白屏或闪白",
    "blurry_motion": "边缘变化很少，疑似模糊或信息量不足",
    "usable_style_candidate": "本地粗筛未发现明显问题",
}


def summarize_datasets(datasets: list[dict[str, Any]], images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summarized = []
    for dataset in datasets:
        rows = [image for image in images if image.get("datasetId") == dataset.get("id")]
        summarized.append({
            **dataset,
            "totalImages": len(rows),
            "selectedImages": len([image for image in rows if image.get("selected", True) is not False]),
            "captionLocked": len([image for image in rows if image.get("captionLocked")]),
            "unannotated": len([image for image in rows if image.get("annotation") != "已标注"]),
        })
    return summarized


def list_datasets() -> list[dict[str, Any]]:
    datasets = read_json(DATASETS_PATH, [])
    images = read_json(IMAGES_PATH, [])
    return summarize_datasets(datasets, images)


def normalized_image(image: dict[str, Any]) -> dict[str, Any]:
    normalized = {**image}
    normalized["annotation"] = "已标注" if image.get("annotation") == "已标注" else "未标注"
    if "selected" not in normalized:
        normalized["selected"] = True
    llm_quality_score = (normalized.get("llmClassification") or {}).get("qualityScore")
    if llm_quality_score is None:
        normalized.pop("qualityScore", None)
    else:
        normalized["qualityScore"] = llm_quality_score
    return normalized


def dataset_images_from(images: list[dict[str, Any]], dataset_id: str) -> list[dict[str, Any]]:
    return [normalized_image(image) for image in images if image.get("datasetId") == dataset_id]


def create_dataset(body: dict[str, Any]) -> dict[str, Any]:
    datasets = read_json(DATASETS_PATH, [])
    dataset = {
        "id": unique_id(body.get("id") or body.get("name"), "dataset", datasets),
        "name": body.get("name") or "未命名数据集",
        "domain": body.get("domain") or "混合",
        "trigger": body.get("trigger") or "custom_trigger",
        "build": "草稿",
        "status": "整理中",
        "createdAt": now_iso(),
    }
    datasets.append(dataset)
    write_json(DATASETS_PATH, datasets)
    return dataset


def list_dataset_images(dataset_id: str) -> list[dict[str, Any]]:
    images = read_json(IMAGES_PATH, [])
    return dataset_images_from(images, dataset_id)


def safe_image_name(value: str) -> str:
    stem = Path(value or "image").stem or "image"
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", stem).strip("._") or "image"


def dataset_image_path(dataset_id: str, image: dict[str, Any]) -> Path:
    frame_path = str(image.get("framePath") or "")
    if not frame_path:
        raise RuntimeError("图片记录缺少 framePath")
    sources_root = (DATA_ROOT / "datasets" / dataset_id / "sources").resolve()
    file_path = (sources_root / Path(frame_path)).resolve()
    if sources_root not in file_path.parents:
        raise RuntimeError("图片路径不在数据集目录内")
    if not file_path.is_file():
        raise RuntimeError(f"图片文件不存在：{file_path}")
    return file_path


def dataset_image_file_response(dataset_id: str, image_id: str) -> FileResponse:
    image = next((item for item in list_dataset_images(dataset_id) if item.get("id") == image_id), None)
    if not image:
        raise RuntimeError(f"图片不存在：{image_id}")
    file_path = dataset_image_path(dataset_id, image)
    return FileResponse(file_path, media_type="image/jpeg", filename=file_path.name)


def sample_grayscale(file_path: Path, sample_size: int = 64) -> list[int]:
    with Image.open(file_path) as opened:
        resampling = getattr(Image, "Resampling", Image).LANCZOS
        gray = opened.convert("L").resize((sample_size, sample_size), resampling)
        return list(gray.getdata())


def edge_score(pixels: list[int], size: int) -> float:
    diffs: list[int] = []
    for y in range(size):
        row_start = y * size
        for x in range(size - 1):
            diffs.append(abs(pixels[row_start + x] - pixels[row_start + x + 1]))
    for y in range(size - 1):
        row_start = y * size
        next_row_start = (y + 1) * size
        for x in range(size):
            diffs.append(abs(pixels[row_start + x] - pixels[next_row_start + x]))
    return mean(diffs) if diffs else 0.0


def ahash(pixels: list[int], size: int) -> int:
    block = max(1, size // 8)
    values: list[float] = []
    for by in range(8):
        for bx in range(8):
            sample: list[int] = []
            for y in range(by * block, min((by + 1) * block, size)):
                start = y * size + bx * block
                sample.extend(pixels[start : start + block])
            values.append(mean(sample) if sample else 0.0)
    threshold = mean(values)
    result = 0
    for index, value in enumerate(values):
        if value >= threshold:
            result |= 1 << index
    return result


def analyze_image_file(file_path: Path) -> dict[str, Any]:
    sample_size = 64
    pixels = sample_grayscale(file_path, sample_size)
    luma_mean = mean(pixels)
    luma_std = pstdev(pixels) if len(pixels) > 1 else 0.0
    edge = edge_score(pixels, sample_size)
    frame_hash = ahash(pixels, sample_size)

    labels: list[str] = []
    if luma_mean <= 18 and luma_std <= 12:
        labels.append("black_or_near_black")
    if luma_mean >= 238 and luma_std <= 12:
        labels.append("white_or_flash")
    if edge <= 4.5 and "black_or_near_black" not in labels and "white_or_flash" not in labels:
        labels.append("blurry_motion")
    if not labels:
        labels.append("usable_style_candidate")

    reject_reason = next((label for label in labels if label in REJECT_LABELS), None)
    reasons = [LABEL_REASONS[label] for label in labels if label in LABEL_REASONS]
    metrics = {
        "lumaMean": round(luma_mean, 3),
        "lumaStd": round(luma_std, 3),
        "edgeScore": round(edge, 3),
        "ahash": f"{frame_hash:016x}",
    }
    return {
        "runAt": now_iso(),
        "version": "local-validity-v1",
        "labels": labels,
        "recommendation": "review" if reject_reason else "keep",
        "rejectReason": reject_reason,
        "reasons": reasons,
        "metrics": metrics,
    }


def screen_dataset_images(dataset_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    body = body or {}
    image_ids = set(body.get("imageIds") or [])
    images = read_json(IMAGES_PATH, [])
    updated = 0
    failed = []
    for image in images:
        if image.get("datasetId") != dataset_id:
            continue
        if image_ids and image.get("id") not in image_ids:
            continue
        try:
            screening = analyze_image_file(dataset_image_path(dataset_id, image))
            labels = screening["labels"]
            image["localScreening"] = screening
            image["quality"] = "需复核" if screening.get("rejectReason") else "可用"
            image["suggestion"] = "；".join(screening["reasons"])
            image.pop("qualityScore", None)
            image["updatedAt"] = now_iso()
            updated += 1
        except Exception as error:
            failed.append({"id": image.get("id"), "error": str(error)})
    write_json(IMAGES_PATH, images)
    return {"images": dataset_images_from(images, dataset_id), "updated": updated, "failed": failed}


def import_dataset_image(dataset_id: str, filename: str, content: bytes) -> dict[str, Any]:
    if not content:
        raise RuntimeError("上传图片为空")
    images = read_json(IMAGES_PATH, [])
    image_id = unique_id(safe_image_name(filename), "img", images)
    relative_path = Path("manual_uploads") / f"{image_id}.jpg"
    target_path = DATA_ROOT / "datasets" / dataset_id / "sources" / relative_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from io import BytesIO
        with Image.open(BytesIO(content)) as opened:
            saved = opened.convert("RGB")
            saved.save(target_path, format="JPEG", quality=95)
            width, height = saved.size
    except Exception as error:
        raise RuntimeError(f"图片读取失败：{error}") from error
    image = {
        "id": image_id,
        "datasetId": dataset_id,
        "framePath": str(relative_path).replace("\\", "/"),
        "sourceId": "manual_upload",
        "timestampSec": None,
        "view": "未知",
        "quality": "未检查",
        "annotation": "未标注",
        "selected": True,
        "captionLocked": False,
        "caption": "",
        "suggestion": "",
        "width": width,
        "height": height,
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
    }
    images.append(image)
    write_json(IMAGES_PATH, images)
    return {"image": normalized_image(image), "images": dataset_images_from(images, dataset_id)}


def mark_dataset_images_by_filter(dataset_id: str, body: dict[str, Any]) -> dict[str, Any]:
    labels = {LABEL_ALIASES.get(label, label) for label in body.get("labels") or []}
    quality_values = set(body.get("quality") or [])
    image_ids = set(body.get("imageIds") or [])
    selected = bool(body.get("selected", False))
    reason = body.get("reason") or "批量标记"
    images = read_json(IMAGES_PATH, [])
    updated = 0
    for image in images:
        if image.get("datasetId") != dataset_id:
            continue
        if image_ids:
            matched = image.get("id") in image_ids
        else:
            local_labels = {LABEL_ALIASES.get(label, label) for label in (image.get("localScreening") or {}).get("labels") or []}
            label_matched = bool(labels and local_labels.intersection(labels))
            quality_matched = bool(quality_values and image.get("quality") in quality_values)
            matched = label_matched or quality_matched
        if not matched:
            continue
        image["selected"] = selected
        image["rejectReason"] = reason if not selected else ""
        image["updatedAt"] = now_iso()
        updated += 1
    write_json(IMAGES_PATH, images)
    return {"images": dataset_images_from(images, dataset_id), "updated": updated}


def update_dataset_image(dataset_id: str, image_id: str, body: dict[str, Any]) -> dict[str, Any]:
    images = read_json(IMAGES_PATH, [])
    updated_image: dict[str, Any] | None = None
    for image in images:
        if image.get("datasetId") != dataset_id or image.get("id") != image_id:
            continue
        if "caption" in body:
            caption = str(body.get("caption") or "").strip()
            image["caption"] = caption
            image["captionLocked"] = bool(caption)
            image["annotation"] = "已标注" if caption else "未标注"
        if "selected" in body:
            selected = bool(body.get("selected"))
            image["selected"] = selected
            image["rejectReason"] = "" if selected else (body.get("reason") or "用户手动设置：不参与训练")
        image["updatedAt"] = now_iso()
        updated_image = image
        break
    if not updated_image:
        raise RuntimeError(f"图片不存在：{image_id}")
    write_json(IMAGES_PATH, images)
    return {"image": normalized_image(updated_image), "images": dataset_images_from(images, dataset_id)}
