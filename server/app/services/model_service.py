from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from .runtime_service import control_vllm, vllm_runtime_status

VLLM_IMAGE = "docker.io/vllm/vllm-openai:v0.23.0"

MODEL_ASSETS = [
    {
        "id": "qwen-image-dit",
        "name": "Qwen Image 2512 DiT",
        "kind": "image-generation",
        "path": "/data/models/qwen-image-2512-dit",
        "required": True,
    },
    {
        "id": "qwen-image-vae",
        "name": "Qwen Image VAE",
        "kind": "image-generation",
        "path": "/data/models/qwen-image-vae",
        "required": True,
    },
    {
        "id": "qwen-image-text-encoder",
        "name": "Qwen Image Text Encoder",
        "kind": "image-generation",
        "path": "/data/models/qwen-image-text-encoder",
        "required": True,
    },
    {
        "id": "qwen25-vl-7b",
        "name": "Qwen2.5-VL-7B 标注模型",
        "kind": "annotation",
        "path": "/data/models/qwen2.5-vl-7b-instruct",
        "required": True,
    },
    {
        "id": "musubi-tuner",
        "name": "musubi-tuner",
        "kind": "training",
        "path": "/opt/musubi-tuner",
        "required": True,
    },
]


def command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def run_command(args: list[str], timeout: int = 8) -> dict[str, Any]:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
        return {"ok": result.returncode == 0, "code": result.returncode, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}
    except FileNotFoundError:
        return {"ok": False, "code": None, "stdout": "", "stderr": f"找不到命令：{args[0]}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "code": None, "stdout": "", "stderr": "命令超时"}


def directory_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def format_bytes(value: int) -> str:
    size = float(value)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TB"


def model_asset_status(asset: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(asset["path"]))
    exists = path.exists()
    file_count = 0
    if exists and path.is_dir():
        file_count = sum(1 for item in path.rglob("*") if item.is_file())
    size_bytes = directory_size(path) if exists else 0
    status = "可用" if exists and (path.is_file() or file_count > 0) else "缺失"
    return {**asset, "status": status, "exists": exists, "fileCount": file_count, "sizeBytes": size_bytes, "size": format_bytes(size_bytes)}


def gpu_status() -> dict[str, Any]:
    if not command_exists("nvidia-smi"):
        return {"available": False, "status": "未安装", "message": "找不到 nvidia-smi"}
    query = "name,memory.total,memory.used,driver_version,temperature.gpu,utilization.gpu"
    result = run_command(["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"], timeout=8)
    if not result["ok"]:
        return {"available": False, "status": "失败", "message": result["stderr"] or result["stdout"]}
    gpus = []
    for line in result["stdout"].splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) >= 6:
            gpus.append({
                "name": parts[0],
                "memoryTotalMb": int(float(parts[1])),
                "memoryUsedMb": int(float(parts[2])),
                "driverVersion": parts[3],
                "temperatureC": int(float(parts[4])),
                "utilizationPct": int(float(parts[5])),
            })
    return {"available": bool(gpus), "status": "可用" if gpus else "未知", "gpus": gpus}


def docker_status() -> dict[str, Any]:
    if not command_exists("docker"):
        return {"available": False, "status": "未安装", "vllmImage": VLLM_IMAGE, "imagePresent": False}
    version = run_command(["docker", "--version"])
    image = run_command(["docker", "image", "inspect", VLLM_IMAGE], timeout=12)
    return {
        "available": version["ok"],
        "status": "可用" if version["ok"] else "失败",
        "version": version["stdout"] or version["stderr"],
        "vllmImage": VLLM_IMAGE,
        "imagePresent": image["ok"],
    }


def vllm_status() -> dict[str, Any]:
    image = docker_status()
    return {**image, "status": "镜像已就绪" if image.get("imagePresent") else "未就绪"}


def model_runtime_status() -> dict[str, Any]:
    assets = [model_asset_status(asset) for asset in MODEL_ASSETS]
    gpu = gpu_status()
    docker = docker_status()
    ready_assets = len([asset for asset in assets if asset["status"] == "可用"])
    return {
        "assets": assets,
        "gpu": gpu,
        "docker": docker,
        "vllm": {**vllm_status(), "runtime": vllm_runtime_status()},
        "summary": {
            "assetCount": len(assets),
            "readyAssets": ready_assets,
            "gpuReady": gpu.get("available", False),
            "vllmImageReady": docker.get("imagePresent", False),
            "allReady": ready_assets == len(assets) and gpu.get("available", False) and docker.get("imagePresent", False),
        },
    }


def check_model_asset(asset_id: str) -> dict[str, Any]:
    if asset_id == "gpu":
        return {"id": "gpu", **gpu_status()}
    if asset_id == "vllm":
        return {"id": "vllm", **vllm_status()}
    asset = next((item for item in MODEL_ASSETS if item["id"] == asset_id), None)
    if not asset:
        raise RuntimeError(f"未知模型资产：{asset_id}")
    return model_asset_status(asset)


def control_vllm_service(action: str) -> dict[str, Any]:
    return control_vllm(action)
