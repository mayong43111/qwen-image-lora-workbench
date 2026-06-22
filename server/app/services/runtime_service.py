from __future__ import annotations

import shutil
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any

VLLM_SERVICE = "qwen-vllm-annotator"
VLLM_MODELS_URL = "http://127.0.0.1:8000/v1/models"
VLLM_READY_TIMEOUT_SECONDS = 420


def command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def run_command(args: list[str], timeout: int = 20) -> dict[str, Any]:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
        return {"ok": result.returncode == 0, "code": result.returncode, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}
    except FileNotFoundError:
        return {"ok": False, "code": None, "stdout": "", "stderr": f"找不到命令：{args[0]}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "code": None, "stdout": "", "stderr": "命令超时"}


def systemctl_available() -> bool:
    return command_exists("systemctl")


def service_active(service: str = VLLM_SERVICE) -> bool:
    if not systemctl_available():
        return False
    result = run_command(["systemctl", "is-active", "--quiet", service], timeout=8)
    return bool(result["ok"])


def vllm_endpoint_ready(timeout_seconds: int = 3) -> bool:
    deadline = time.time() + timeout_seconds
    while True:
        try:
            with urllib.request.urlopen(VLLM_MODELS_URL, timeout=3) as response:
                if 200 <= response.status < 300:
                    return True
        except (urllib.error.URLError, TimeoutError):
            pass
        if time.time() >= deadline:
            return False
        time.sleep(2)


def vllm_runtime_status() -> dict[str, Any]:
    active = service_active()
    ready = vllm_endpoint_ready(1) if active else False
    return {
        "service": VLLM_SERVICE,
        "serviceControlAvailable": systemctl_available(),
        "active": active,
        "ready": ready,
        "endpoint": VLLM_MODELS_URL,
        "status": "可用" if ready else ("启动中" if active else "已停止"),
    }


def control_vllm(action: str, wait_ready: bool = True) -> dict[str, Any]:
    if action not in {"start", "stop", "restart"}:
        raise RuntimeError(f"不支持的 vLLM 操作：{action}")
    if not systemctl_available():
        raise RuntimeError("当前环境没有 systemctl，无法控制本机 vLLM 服务")
    result = run_command(["sudo", "systemctl", action, VLLM_SERVICE], timeout=60)
    if not result["ok"]:
        raise RuntimeError(result["stderr"] or result["stdout"] or f"systemctl {action} 失败")
    if action in {"start", "restart"} and wait_ready:
        if not vllm_endpoint_ready(VLLM_READY_TIMEOUT_SECONDS):
            raise RuntimeError(f"vLLM 服务已启动，但 {VLLM_MODELS_URL} 未在 {VLLM_READY_TIMEOUT_SECONDS} 秒内就绪")
    return vllm_runtime_status()


def ensure_vllm_running(wait_ready: bool = True) -> dict[str, Any]:
    if not service_active():
        return control_vllm("start", wait_ready=wait_ready)
    if wait_ready and not vllm_endpoint_ready(3):
        if not vllm_endpoint_ready(VLLM_READY_TIMEOUT_SECONDS):
            raise RuntimeError(f"vLLM 服务正在运行，但 {VLLM_MODELS_URL} 未在 {VLLM_READY_TIMEOUT_SECONDS} 秒内就绪")
    return vllm_runtime_status()


def stop_vllm_if_running() -> bool:
    was_running = service_active()
    if was_running:
        control_vllm("stop", wait_ready=False)
    return was_running