from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT

resolved_ffmpeg_path: str | None = None
resolved_aria2c_path: str | None = None


def run_process(command: str, args: list[str], cwd: Path | None = None, extra_path: list[Path] | None = None, cancel_checker: Any | None = None) -> dict[str, Any]:
    try:
        env = os.environ.copy()
        if extra_path:
            path_value = env.get("PATH", "")
            env["PATH"] = os.pathsep.join([str(path) for path in extra_path]) + os.pathsep + path_value
        child = subprocess.Popen(
            [command, *args],
            cwd=str(cwd) if cwd else None,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
        )
        while child.poll() is None:
            if cancel_checker and cancel_checker():
                child.terminate()
                try:
                    stdout, stderr = child.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    stdout, stderr = child.communicate()
                return {"code": -2, "stdout": stdout, "stderr": stderr, "cancelled": True}
            time.sleep(0.2)
        stdout, stderr = child.communicate()
        return {"code": child.returncode, "stdout": stdout, "stderr": stderr}
    except FileNotFoundError:
        return {"code": -1, "stdout": "", "stderr": f"{command} 未安装或不在 PATH"}


def first_existing_executable(paths: list[Path]) -> str | None:
    for candidate in paths:
        if candidate.is_file():
            return str(candidate)
    return None


def find_executable_under(root: Path, name: str, max_matches: int = 1) -> str | None:
    if not root.exists():
        return None
    try:
        for index, candidate in enumerate(root.rglob(name)):
            if candidate.is_file():
                return str(candidate)
            if index >= max_matches:
                break
    except OSError:
        return None
    return None


def resolve_ffmpeg() -> str:
    global resolved_ffmpeg_path
    if resolved_ffmpeg_path and Path(resolved_ffmpeg_path).is_file():
        return resolved_ffmpeg_path

    explicit_path = os.environ.get("FFMPEG_PATH")
    if explicit_path and Path(explicit_path).is_file():
        resolved_ffmpeg_path = explicit_path
        return resolved_ffmpeg_path

    path_command = shutil.which("ffmpeg")
    if path_command:
        resolved_ffmpeg_path = path_command
        return resolved_ffmpeg_path

    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    user_profile = Path(os.environ.get("USERPROFILE", ""))
    program_files = Path(os.environ.get("ProgramFiles", ""))
    program_files_x86 = Path(os.environ.get("ProgramFiles(x86)", ""))
    candidates = [
        PROJECT_ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe",
        PROJECT_ROOT / "ffmpeg" / "bin" / "ffmpeg.exe",
        Path("C:/ffmpeg/bin/ffmpeg.exe"),
        Path("C:/tools/ffmpeg/bin/ffmpeg.exe"),
        user_profile / "scoop" / "shims" / "ffmpeg.exe",
        user_profile / "scoop" / "apps" / "ffmpeg" / "current" / "bin" / "ffmpeg.exe",
        program_files / "ffmpeg" / "bin" / "ffmpeg.exe",
        program_files_x86 / "ffmpeg" / "bin" / "ffmpeg.exe",
    ]
    existing = first_existing_executable(candidates)
    if existing:
        resolved_ffmpeg_path = existing
        return resolved_ffmpeg_path

    winget_match = find_executable_under(local_app_data / "Microsoft" / "WinGet" / "Packages", "ffmpeg.exe")
    if winget_match:
        resolved_ffmpeg_path = winget_match
        return resolved_ffmpeg_path

    raise RuntimeError("ffmpeg 未找到：请设置 FFMPEG_PATH，或把 ffmpeg.exe 所在目录加入 VS Code 启动环境的 PATH")


def resolve_aria2c() -> str:
    global resolved_aria2c_path
    if resolved_aria2c_path and Path(resolved_aria2c_path).is_file():
        return resolved_aria2c_path

    explicit_path = os.environ.get("ARIA2C_PATH")
    if explicit_path and Path(explicit_path).is_file():
        resolved_aria2c_path = explicit_path
        return resolved_aria2c_path

    path_command = shutil.which("aria2c")
    if path_command:
        resolved_aria2c_path = path_command
        return resolved_aria2c_path

    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    user_profile = Path(os.environ.get("USERPROFILE", ""))
    program_files = Path(os.environ.get("ProgramFiles", ""))
    program_files_x86 = Path(os.environ.get("ProgramFiles(x86)", ""))
    candidates = [
        PROJECT_ROOT / "tools" / "aria2" / "aria2c.exe",
        PROJECT_ROOT / "tools" / "aria2" / "aria2c",
        Path("C:/aria2/aria2c.exe"),
        Path("C:/tools/aria2/aria2c.exe"),
        user_profile / "scoop" / "shims" / "aria2c.exe",
        user_profile / "scoop" / "apps" / "aria2" / "current" / "aria2c.exe",
        program_files / "aria2" / "aria2c.exe",
        program_files_x86 / "aria2" / "aria2c.exe",
    ]
    existing = first_existing_executable(candidates)
    if existing:
        resolved_aria2c_path = existing
        return resolved_aria2c_path

    winget_match = find_executable_under(local_app_data / "Microsoft" / "WinGet" / "Packages", "aria2c.exe")
    if winget_match:
        resolved_aria2c_path = winget_match
        return resolved_aria2c_path

    raise RuntimeError("aria2c 未找到：磁力链接解析和下载需要安装 aria2，或设置 ARIA2C_PATH")
