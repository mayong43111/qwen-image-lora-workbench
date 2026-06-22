from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from fastapi.responses import FileResponse

from ..core.config import DATASETS_PATH, EVALUATIONS_PATH, EVALUATION_RUNS_DIR, IMAGES_PATH, LORAS_PATH, TRAINING_RUNS_DIR
from ..core.storage import now_iso, read_json, safe_id, unique_id, write_json
from .dataset_service import dataset_image_path, list_datasets
from .task_service import create_task, update_task


def list_loras() -> list[dict[str, Any]]:
    return read_json(LORAS_PATH, [])


def list_evaluations() -> list[dict[str, Any]]:
    return read_json(EVALUATIONS_PATH, [])


def evaluation_by_id(evaluation_id: str) -> dict[str, Any]:
    evaluation = next((item for item in list_evaluations() if item.get("id") == evaluation_id), None)
    if not evaluation:
        raise RuntimeError(f"测试生成记录不存在：{evaluation_id}")
    return evaluation


def save_evaluations(evaluations: list[dict[str, Any]]) -> None:
    write_json(EVALUATIONS_PATH, evaluations)


def dataset_by_id(dataset_id: str) -> dict[str, Any]:
    dataset = next((item for item in list_datasets() if item.get("id") == dataset_id), None)
    if not dataset:
        raise RuntimeError(f"数据集不存在：{dataset_id}")
    return dataset


def selected_training_images(dataset_id: str) -> list[dict[str, Any]]:
    images = read_json(IMAGES_PATH, [])
    return [image for image in images if image.get("datasetId") == dataset_id and image.get("selected", True) is not False]


def image_caption(image: dict[str, Any]) -> str:
    llm = image.get("llmClassification") or {}
    return str(image.get("caption") or llm.get("captionSuggestion") or image.get("suggestion") or "").strip()


def create_training_manifest(dataset: dict[str, Any], images: list[dict[str, Any]], run_dir: Path) -> dict[str, Any]:
    manifest_path = run_dir / "dataset_manifest.jsonl"
    rows: list[dict[str, Any]] = []
    missing_caption: list[str] = []
    for image in images:
        caption = image_caption(image)
        if not caption:
            missing_caption.append(str(image.get("id")))
        rows.append({
            "image_id": image.get("id"),
            "image_path": str(dataset_image_path(str(dataset["id"]), image)),
            "caption": caption,
            "width": image.get("width"),
            "height": image.get("height"),
            "quality_score": (image.get("llmClassification") or {}).get("qualityScore"),
            "category": (image.get("llmClassification") or {}).get("category"),
            "tags": (image.get("llmClassification") or {}).get("tags") or [],
        })
    manifest_path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")
    return {"path": str(manifest_path), "rows": len(rows), "missingCaptionIds": missing_caption}


def create_training_job(body: dict[str, Any]) -> dict[str, Any]:
    dataset_id = str(body.get("datasetId") or "")
    if not dataset_id:
        raise RuntimeError("必须选择数据集")
    dataset = dataset_by_id(dataset_id)
    images = selected_training_images(dataset_id)
    if not images:
        raise RuntimeError("没有参与训练的图片，请先在数据集页选择图片")

    timestamp = int(time.time() * 1000)
    run_id = safe_id(f"train_{dataset_id}_{timestamp}", "train")
    run_dir = TRAINING_RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = create_training_manifest(dataset, images, run_dir)

    config = {
        "runId": run_id,
        "datasetId": dataset_id,
        "datasetName": dataset.get("name"),
        "trigger": dataset.get("trigger"),
        "baseModel": body.get("baseModel") or "Qwen Image",
        "resolution": int(body.get("resolution") or 1024),
        "steps": int(body.get("steps") or max(100, len(images) * 3)),
        "rank": int(body.get("rank") or 16),
        "learningRate": body.get("learningRate") or "1e-4",
        "batchSize": int(body.get("batchSize") or 1),
        "seed": int(body.get("seed") or 42),
        "imageCount": len(images),
        "manifestPath": manifest["path"],
        "outputDir": str(run_dir / "output"),
        "gpuCommand": body.get("gpuCommand") or "musubi-tuner training command will be filled on GPU VM",
        "createdAt": now_iso(),
    }
    (run_dir / "train_config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    loras = list_loras()
    lora = {
        "id": unique_id(f"lora_{dataset_id}_{timestamp}", "lora", loras),
        "name": body.get("name") or f"{dataset.get('name')} LoRA",
        "datasetId": dataset_id,
        "build": dataset.get("build") or "草稿",
        "trigger": dataset.get("trigger"),
        "baseModel": config["baseModel"],
        "strength": float(body.get("strength") or 0.8),
        "status": "等待GPU训练",
        "runId": run_id,
        "runDir": str(run_dir),
        "configPath": str(run_dir / "train_config.json"),
        "manifestPath": manifest["path"],
        "outputDir": config["outputDir"],
        "imageCount": len(images),
        "missingCaptionCount": len(manifest["missingCaptionIds"]),
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
    }
    loras.insert(0, lora)
    write_json(LORAS_PATH, loras)

    task = create_task("LoRA训练准备", lora["name"], {"runId": run_id, "datasetId": dataset_id, "loraId": lora["id"], "configPath": lora["configPath"], "manifestPath": lora["manifestPath"]})
    task_patch = {"status": "等待GPU", "progress": 100, "output": {"loraId": lora["id"], "runDir": str(run_dir), "missingCaptionIds": manifest["missingCaptionIds"]}}
    update_task(task["id"], task_patch)
    task = {**task, **task_patch}
    return {"lora": lora, "run": config, "manifest": manifest, "task": task}


def update_lora(lora_id: str, body: dict[str, Any]) -> dict[str, Any]:
    loras = list_loras()
    index = next((i for i, item in enumerate(loras) if item.get("id") == lora_id), -1)
    if index < 0:
        raise RuntimeError(f"LoRA 不存在：{lora_id}")
    allowed = {"name", "status", "strength", "weightPath", "notes"}
    patch = {key: value for key, value in body.items() if key in allowed}
    loras[index] = {**loras[index], **patch, "updatedAt": now_iso()}
    write_json(LORAS_PATH, loras)
    return loras[index]


def create_evaluation_job(body: dict[str, Any]) -> dict[str, Any]:
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise RuntimeError("必须填写 Prompt")
    lora_id = str(body.get("loraId") or "")
    lora = next((item for item in list_loras() if item.get("id") == lora_id), None) if lora_id else None
    timestamp = int(time.time() * 1000)
    run_id = safe_id(f"eval_{lora_id or 'base'}_{timestamp}", "eval")
    run_dir = EVALUATION_RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    count = max(1, min(8, int(body.get("count") or 1)))
    seed = int(body.get("seed") or 42)
    evaluation = {
        "id": unique_id(run_id, "eval", list_evaluations()),
        "runId": run_id,
        "loraId": lora_id or None,
        "loraName": lora.get("name") if lora else "基础模型",
        "prompt": prompt,
        "negativePrompt": body.get("negativePrompt") or "",
        "seed": seed,
        "count": count,
        "width": int(body.get("width") or 1024),
        "height": int(body.get("height") or 1024),
        "steps": int(body.get("steps") or 30),
        "guidanceScale": float(body.get("guidanceScale") or 4.0),
        "status": "等待GPU生成",
        "runDir": str(run_dir),
        "results": [{"id": f"{run_id}_{index}", "seed": seed + index, "status": "等待GPU生成"} for index in range(count)],
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
    }
    (run_dir / "generation_request.json").write_text(json.dumps(evaluation, ensure_ascii=False, indent=2), encoding="utf-8")
    evaluations = list_evaluations()
    evaluations.insert(0, evaluation)
    write_json(EVALUATIONS_PATH, evaluations)
    task = create_task("测试生成准备", evaluation["loraName"], {"evaluationId": evaluation["id"], "runId": run_id, "runDir": str(run_dir)})
    task_patch = {"status": "等待GPU", "progress": 100, "output": {"evaluationId": evaluation["id"], "runDir": str(run_dir)}}
    update_task(task["id"], task_patch)
    task = {**task, **task_patch}
    return {"evaluation": evaluation, "task": task}


def update_evaluation(evaluation_id: str, body: dict[str, Any]) -> dict[str, Any]:
    evaluations = list_evaluations()
    index = next((i for i, item in enumerate(evaluations) if item.get("id") == evaluation_id), -1)
    if index < 0:
        raise RuntimeError(f"测试生成记录不存在：{evaluation_id}")
    allowed = {"status", "notes", "prompt", "negativePrompt", "seed", "steps", "guidanceScale"}
    patch = {key: value for key, value in body.items() if key in allowed}
    evaluations[index] = {**evaluations[index], **patch, "updatedAt": now_iso()}
    save_evaluations(evaluations)
    return evaluations[index]


def update_evaluation_result(evaluation_id: str, result_id: str, body: dict[str, Any]) -> dict[str, Any]:
    evaluations = list_evaluations()
    evaluation_index = next((i for i, item in enumerate(evaluations) if item.get("id") == evaluation_id), -1)
    if evaluation_index < 0:
        raise RuntimeError(f"测试生成记录不存在：{evaluation_id}")
    results = evaluations[evaluation_index].get("results") or []
    result_index = next((i for i, item in enumerate(results) if item.get("id") == result_id), -1)
    if result_index < 0:
        raise RuntimeError(f"生成结果不存在：{result_id}")
    allowed = {"status", "seed", "imagePath", "imageUrl", "error", "metrics", "notes"}
    patch = {key: value for key, value in body.items() if key in allowed}
    if patch.get("imagePath") and not patch.get("imageUrl"):
        patch["imageUrl"] = f"/api/evaluations/{evaluation_id}/results/{result_id}/file"
    results[result_index] = {**results[result_index], **patch, "updatedAt": now_iso()}
    if results[result_index].get("imagePath") and results[result_index].get("status") in (None, "等待GPU生成"):
        results[result_index]["status"] = "完成"
    evaluations[evaluation_index]["results"] = results
    if all(result.get("status") == "完成" for result in results):
        evaluations[evaluation_index]["status"] = "完成"
    elif any(result.get("status") == "完成" for result in results):
        evaluations[evaluation_index]["status"] = "部分完成"
    elif any(result.get("status") == "失败" for result in results):
        evaluations[evaluation_index]["status"] = "失败"
    evaluations[evaluation_index]["updatedAt"] = now_iso()
    save_evaluations(evaluations)
    return evaluations[evaluation_index]


def import_evaluation_result_file(evaluation_id: str, result_id: str, filename: str, content: bytes) -> dict[str, Any]:
    evaluation = evaluation_by_id(evaluation_id)
    result = next((item for item in evaluation.get("results") or [] if item.get("id") == result_id), None)
    if not result:
        raise RuntimeError(f"生成结果不存在：{result_id}")
    suffix = Path(filename or "result.png").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        suffix = ".png"
    run_dir = Path(str(evaluation.get("runDir") or (EVALUATION_RUNS_DIR / str(evaluation.get("runId") or evaluation_id))))
    output_dir = run_dir / "results"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{result_id}{suffix}"
    output_path.write_bytes(content)
    return update_evaluation_result(evaluation_id, result_id, {"status": "完成", "imagePath": str(output_path), "imageUrl": f"/api/evaluations/{evaluation_id}/results/{result_id}/file"})


def evaluation_result_file_response(evaluation_id: str, result_id: str) -> FileResponse:
    evaluation = evaluation_by_id(evaluation_id)
    result = next((item for item in evaluation.get("results") or [] if item.get("id") == result_id), None)
    if not result or not result.get("imagePath"):
        raise RuntimeError("生成结果还没有图片")
    file_path = Path(str(result["imagePath"])).resolve()
    runs_root = EVALUATION_RUNS_DIR.resolve()
    if runs_root not in file_path.parents:
        raise RuntimeError("生成图片路径不在评测目录内")
    if not file_path.is_file():
        raise RuntimeError(f"生成图片不存在：{file_path}")
    media_type = "image/png" if file_path.suffix.lower() == ".png" else "image/jpeg"
    if file_path.suffix.lower() == ".webp":
        media_type = "image/webp"
    return FileResponse(file_path, media_type=media_type, filename=file_path.name)
