from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from fastapi.responses import FileResponse

from ..core.config import DATASETS_PATH, EVALUATIONS_PATH, EVALUATION_RUNS_DIR, IMAGES_PATH, LORAS_PATH, TRAINING_RUNS_DIR
from ..core.storage import now_iso, read_json, safe_id, unique_id, write_json
from .dataset_service import dataset_image_path, list_datasets
from .runtime_service import control_vllm, stop_vllm_if_running
from .task_service import append_task_log, create_task, is_cancel_requested, mark_cancelled, register_task_process, start_thread, unregister_task_process, update_task


MUSUBI_ROOT = Path(os.environ.get("MUSUBI_TUNER_ROOT", "/opt/musubi-tuner"))
MUSUBI_PYTHON = Path(os.environ.get("MUSUBI_TUNER_PYTHON", str(MUSUBI_ROOT / ".venv" / "bin" / "python")))
MUSUBI_ACCELERATE = Path(os.environ.get("MUSUBI_TUNER_ACCELERATE", str(MUSUBI_ROOT / ".venv" / "bin" / "accelerate")))
QWEN_IMAGE_MODEL_ROOT = Path(os.environ.get("QWEN_IMAGE_MODEL_ROOT", "/data/models/qwen-image-2512-dit"))
QWEN_IMAGE_DIT = Path(os.environ.get("QWEN_IMAGE_DIT", str(QWEN_IMAGE_MODEL_ROOT / "transformer" / "diffusion_pytorch_model-00001-of-00009.safetensors")))
QWEN_IMAGE_VAE = Path(os.environ.get("QWEN_IMAGE_VAE", str(QWEN_IMAGE_MODEL_ROOT / "vae" / "diffusion_pytorch_model.safetensors")))
QWEN_IMAGE_TEXT_ENCODER = Path(os.environ.get("QWEN_IMAGE_TEXT_ENCODER", str(QWEN_IMAGE_MODEL_ROOT / "text_encoder" / "model-00001-of-00004.safetensors")))


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


def toml_string(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def write_training_dataset_config(dataset: dict[str, Any], images: list[dict[str, Any]], run_dir: Path, resolution: int, batch_size: int) -> dict[str, Any]:
    image_dir = run_dir / "prepared_images"
    image_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []
    for index, image in enumerate(images):
        caption = image_caption(image)
        if not caption:
            continue
        source_path = dataset_image_path(str(dataset["id"]), image)
        if not source_path.is_file():
            continue
        suffix = source_path.suffix.lower() or ".jpg"
        image_name = f"{index:05d}_{safe_id(str(image.get('id') or index), 'img')}{suffix}"
        target_path = image_dir / image_name
        shutil.copy2(source_path, target_path)
        caption_path = target_path.with_suffix(".txt")
        caption_path.write_text(caption, encoding="utf-8")
        rows.append({"imagePath": str(target_path), "captionPath": str(caption_path)})
    if not rows:
        raise RuntimeError("没有带 caption 的训练图片，请先完成标注或填写 caption")

    dataset_config_path = run_dir / "dataset_config.toml"
    dataset_config = "\n".join([
        "[general]",
        "caption_extension = \".txt\"",
        "",
        "[[datasets]]",
        f"image_directory = {toml_string(image_dir)}",
        "caption_extension = \".txt\"",
        f"resolution = [{resolution}, {resolution}]",
        f"batch_size = {batch_size}",
        "enable_bucket = true",
        "bucket_no_upscale = false",
        f"cache_directory = {toml_string(run_dir / 'cache')}",
        "",
    ])
    dataset_config_path.write_text(dataset_config, encoding="utf-8")
    return {"path": str(dataset_config_path), "imageDir": str(image_dir), "rows": rows}


def validate_training_runtime(extra_paths: list[Path] | None = None) -> None:
    missing: list[str] = []
    for path, label in [
        (MUSUBI_PYTHON, "musubi Python"),
        (MUSUBI_ACCELERATE, "accelerate"),
        (QWEN_IMAGE_DIT, "Qwen Image DiT"),
        (QWEN_IMAGE_VAE, "Qwen Image VAE"),
        (QWEN_IMAGE_TEXT_ENCODER, "Qwen Image text encoder"),
    ]:
        if not path.exists():
            missing.append(f"{label}: {path}")
    for path in extra_paths or []:
        if not path.exists():
            missing.append(str(path))
    if missing:
        raise RuntimeError(f"训练依赖不存在：{', '.join(missing)}")


def create_training_job(body: dict[str, Any]) -> dict[str, Any]:
    validate_training_runtime()
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
    training_dataset = write_training_dataset_config(dataset, images, run_dir, int(body.get("resolution") or 1024), int(body.get("batchSize") or 1))

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
        "datasetConfigPath": training_dataset["path"],
        "preparedImageDir": training_dataset["imageDir"],
        "outputDir": str(run_dir / "output"),
        "gpuCommand": body.get("gpuCommand") or "由 /api/training/jobs/{runId}/start 启动 musubi-tuner 训练",
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
        "status": "准备中",
        "runId": run_id,
        "runDir": str(run_dir),
        "configPath": str(run_dir / "train_config.json"),
        "datasetConfigPath": training_dataset["path"],
        "manifestPath": manifest["path"],
        "outputDir": config["outputDir"],
        "imageCount": len(images),
        "missingCaptionCount": len(manifest["missingCaptionIds"]),
        "preparedImageCount": len(training_dataset["rows"]),
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
    }
    loras.insert(0, lora)
    write_json(LORAS_PATH, loras)

    task = start_training_run(run_id)
    return {"lora": lora, "run": config, "manifest": manifest, "task": task}


def lora_by_run_id(run_id: str) -> dict[str, Any] | None:
    return next((item for item in list_loras() if item.get("runId") == run_id), None)


def latest_resume_state(output_dir: Path) -> str:
    if not output_dir.is_dir():
        return ""
    candidates = [path for path in output_dir.glob("**/*") if path.is_dir() and "state" in path.name.lower()]
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return str(candidates[0]) if candidates else ""


def build_training_commands(config: dict[str, Any]) -> list[dict[str, Any]]:
    dataset_config = str(config.get("datasetConfigPath") or "")
    output_dir = str(config.get("outputDir") or "")
    output_name = safe_id(str(config.get("runId") or "qwen_image_lora"), "lora")
    steps = str(int(config.get("steps") or 100))
    save_every_n_steps = str(max(1, int(config.get("saveEveryNSteps") or min(100, max(1, int(config.get("steps") or 100))))))
    rank = str(int(config.get("rank") or 16))
    learning_rate = str(config.get("learningRate") or "1e-4")
    seed = str(int(config.get("seed") or 42))
    resume_from_state = str(config.get("resumeFromState") or "")
    train_script = MUSUBI_ROOT / "qwen_image_train_network.py"
    cache_latents_script = MUSUBI_ROOT / "qwen_image_cache_latents.py"
    cache_text_script = MUSUBI_ROOT / "qwen_image_cache_text_encoder_outputs.py"
    train_args = [
        "launch", "--num_cpu_threads_per_process", "1", "--mixed_precision", "bf16", str(train_script),
        "--dit", str(QWEN_IMAGE_DIT),
        "--vae", str(QWEN_IMAGE_VAE),
        "--text_encoder", str(QWEN_IMAGE_TEXT_ENCODER),
        "--model_version", "original",
        "--dataset_config", dataset_config,
        "--sdpa", "--mixed_precision", "bf16",
        "--timestep_sampling", "shift",
        "--weighting_scheme", "none", "--discrete_flow_shift", "2.2",
        "--optimizer_type", "adamw8bit", "--learning_rate", learning_rate, "--gradient_checkpointing",
        "--max_data_loader_n_workers", "2", "--persistent_data_loader_workers",
        "--network_module", "networks.lora_qwen_image",
        "--network_dim", rank,
        "--max_train_steps", steps,
        "--save_every_n_steps", save_every_n_steps,
        "--save_state",
        "--seed", seed,
        "--output_dir", output_dir,
        "--output_name", output_name,
    ]
    if resume_from_state:
        train_args.extend(["--resume", resume_from_state])
    return [
        {
            "name": "缓存 latents",
            "command": str(MUSUBI_PYTHON),
            "args": [str(cache_latents_script), "--dataset_config", dataset_config, "--vae", str(QWEN_IMAGE_VAE), "--model_version", "original", "--batch_size", "1", "--skip_existing"],
        },
        {
            "name": "缓存文本编码",
            "command": str(MUSUBI_PYTHON),
            "args": [str(cache_text_script), "--dataset_config", dataset_config, "--text_encoder", str(QWEN_IMAGE_TEXT_ENCODER), "--batch_size", "1", "--model_version", "original", "--skip_existing"],
        },
        {
            "name": "训练 LoRA",
            "command": str(MUSUBI_ACCELERATE),
            "args": train_args,
        },
    ]


def update_lora_by_id(lora_id: str, patch: dict[str, Any]) -> None:
    loras = list_loras()
    index = next((i for i, item in enumerate(loras) if item.get("id") == lora_id), -1)
    if index < 0:
        return
    loras[index] = {**loras[index], **patch, "updatedAt": now_iso()}
    write_json(LORAS_PATH, loras)


def run_logged_process(task_id_value: str, command: str, args: list[str], cwd: Path, env: dict[str, str]) -> int:
    child = subprocess.Popen(
        [command, *args],
        cwd=str(cwd),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    register_task_process(task_id_value, child)
    try:
        assert child.stdout is not None
        for line in child.stdout:
            text = line.rstrip()
            if text:
                append_task_log(task_id_value, text)
            if is_cancel_requested(task_id_value) and child.poll() is None:
                child.terminate()
        return child.wait()
    finally:
        unregister_task_process(task_id_value)


def training_worker(task: dict[str, Any], run_id: str, lora_id: str, config: dict[str, Any]) -> None:
    update_task(task["id"], {"status": "运行中", "progress": 1})
    update_lora_by_id(lora_id, {"status": "训练中"})
    restore_vllm = False
    output_dir = Path(str(config.get("outputDir")))
    output_dir.mkdir(parents=True, exist_ok=True)
    run_dir = output_dir.parent
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    resume_from_state = latest_resume_state(output_dir)
    if resume_from_state:
        config = {**config, "resumeFromState": resume_from_state}
        append_task_log(task["id"], f"检测到训练 state，恢复来源：{resume_from_state}")
    commands = build_training_commands(config)
    (run_dir / "musubi_commands.json").write_text(json.dumps(commands, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        restore_vllm = stop_vllm_if_running()
        if restore_vllm:
            append_task_log(task["id"], "训练前已自动停止本地 vLLM 标注服务以释放 GPU 显存")
        for index, step in enumerate(commands, start=1):
            if is_cancel_requested(task["id"]):
                mark_cancelled(task["id"])
                update_lora_by_id(lora_id, {"status": "已取消"})
                return
            append_task_log(task["id"], f"开始：{step['name']}\n{step['command']} {' '.join(step['args'])}")
            update_task(task["id"], {"progress": min(95, (index - 1) * 30 + 5), "output": {"runId": run_id, "loraId": lora_id, "currentStep": step["name"]}})
            code = run_logged_process(task["id"], str(step["command"]), list(step["args"]), MUSUBI_ROOT, env)
            if is_cancel_requested(task["id"]):
                mark_cancelled(task["id"])
                update_lora_by_id(lora_id, {"status": "已取消"})
                return
            if code != 0:
                update_task(task["id"], {"status": "失败", "progress": 100, "error": f"{step['name']} 退出码：{code}"})
                update_lora_by_id(lora_id, {"status": "失败"})
                return
        candidates = sorted(output_dir.glob("*.safetensors"), key=lambda path: path.stat().st_mtime, reverse=True)
        weight_path = str(candidates[0]) if candidates else ""
        update_task(task["id"], {"status": "完成", "progress": 100, "output": {"runId": run_id, "loraId": lora_id, "outputDir": str(output_dir), "weightPath": weight_path}})
        update_lora_by_id(lora_id, {"status": "可用" if weight_path else "训练完成", "weightPath": weight_path, "outputDir": str(output_dir)})
    except Exception as error:
        update_task(task["id"], {"status": "失败", "progress": 100, "error": str(error)})
        update_lora_by_id(lora_id, {"status": "失败"})
    finally:
        if restore_vllm:
            try:
                control_vllm("start", wait_ready=False)
                append_task_log(task["id"], "训练任务结束后已自动启动本地 vLLM 标注服务")
            except Exception as error:
                append_task_log(task["id"], f"自动恢复本地 vLLM 失败：{error}")


def start_training_run(run_id: str) -> dict[str, Any]:
    lora = lora_by_run_id(run_id)
    if not lora:
        raise RuntimeError(f"训练运行不存在：{run_id}")
    config_path = Path(str(lora.get("configPath") or ""))
    if not config_path.is_file():
        raise RuntimeError(f"训练配置不存在：{config_path}")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    validate_training_runtime([Path(str(config.get("datasetConfigPath") or ""))])
    task = create_task("LoRA训练", str(lora.get("name") or run_id), {"runId": run_id, "loraId": lora["id"], "configPath": str(config_path), "datasetConfigPath": str(config.get("datasetConfigPath"))})
    start_thread(training_worker, task, run_id, str(lora["id"]), config)
    return task


def resume_training_task(task: dict[str, Any]) -> dict[str, Any]:
    run_id = str((task.get("input") or {}).get("runId") or "")
    lora_id = str((task.get("input") or {}).get("loraId") or "")
    if not run_id or not lora_id:
        raise RuntimeError("训练任务缺少 runId 或 loraId，无法恢复")
    lora = lora_by_run_id(run_id)
    if not lora:
        raise RuntimeError(f"训练运行不存在：{run_id}")
    config_path = Path(str(lora.get("configPath") or (task.get("input") or {}).get("configPath") or ""))
    if not config_path.is_file():
        raise RuntimeError(f"训练配置不存在：{config_path}")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    validate_training_runtime([Path(str(config.get("datasetConfigPath") or ""))])
    start_thread(training_worker, task, run_id, lora_id, config)
    return task


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
