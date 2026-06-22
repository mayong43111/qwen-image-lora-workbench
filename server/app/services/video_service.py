from __future__ import annotations

import mimetypes
import re
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse

from ..core.config import DATA_ROOT, PROJECT_ROOT, VIDEOS_DIR, VIDEOS_PATH
from ..core.processes import resolve_aria2c, resolve_ffmpeg, run_process
from ..core.storage import now_iso, read_json, safe_file_name, unique_id, write_json
from .task_service import append_task_log, create_task, is_cancel_requested, mark_cancelled, register_task_process, start_thread, unregister_task_process, update_task


def parse_duration(value: Any) -> float:
    match = re.search(r"(\d+):(\d+):(\d+(?:\.\d+)?)", str(value or ""))
    if not match:
        return 0
    return round((int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))), 2)


def parse_ffmpeg_output(text: str) -> dict[str, Any]:
    duration_match = re.search(r"Duration:\s*([^,]+)", text)
    stream_line = next((line for line in text.splitlines() if "Video:" in line), "")
    resolution_match = re.search(r"(?:,\s*|\s)(\d{2,5})x(\d{2,5})(?:[\s,]|$)", stream_line)
    fps_match = re.search(r"(\d+(?:\.\d+)?)\s*fps", stream_line)
    return {
        "duration": parse_duration(duration_match.group(1) if duration_match else ""),
        "resolution": f"{resolution_match.group(1)}x{resolution_match.group(2)}" if resolution_match else "未知",
        "fps": float(fps_match.group(1)) if fps_match else 0,
    }


def probe_video(local_path: Any) -> dict[str, Any]:
    path = Path(str(local_path)).resolve()
    if not path.exists():
        raise RuntimeError(f"视频文件不存在：{path}")
    ffmpeg_command = resolve_ffmpeg()
    result = run_process(ffmpeg_command, ["-hide_banner", "-i", str(path)])
    ffmpeg_text = f"{result['stderr']}\n{result['stdout']}"
    if "Duration:" in ffmpeg_text and "Video:" in ffmpeg_text:
        return {**parse_ffmpeg_output(ffmpeg_text), "metadataTool": "ffmpeg", "metadataToolPath": ffmpeg_command}
    raise RuntimeError(f"ffmpeg 识别失败：{result['stderr'] or result['stdout']}")


def list_videos() -> list[dict[str, Any]]:
    return read_json(VIDEOS_PATH, [])


def get_video(video_id: str) -> dict[str, Any]:
    video = next((item for item in list_videos() if item.get("id") == video_id), None)
    if not video:
        raise RuntimeError(f"视频不存在：{video_id}")
    return video


def create_video_from_local_path(body: dict[str, Any], source: str = "本地导入") -> dict[str, Any]:
    if not body.get("localPath"):
        raise RuntimeError("必须提供本地视频路径")
    local_path = Path(str(body["localPath"])).resolve()
    metadata = {"duration": 0, "resolution": "待识别", "fps": 0}
    status = "可用"
    metadata_error = ""
    try:
        metadata = probe_video(local_path)
    except Exception as error:
        status = "待识别"
        metadata_error = str(error)
    videos = read_json(VIDEOS_PATH, [])
    file_name = local_path.name
    video = {
        "id": unique_id(body.get("title") or file_name, "video", videos),
        "title": body.get("title") or file_name,
        "name": file_name,
        "source": source,
        "localPath": str(local_path),
        **metadata,
        "status": status,
        "metadataError": metadata_error,
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
    }
    videos.insert(0, video)
    write_json(VIDEOS_PATH, videos)
    return video


async def import_uploaded_video(request: Request, filename: str, title: str | None) -> dict[str, Any]:
    content = await request.body()
    if not content:
        raise RuntimeError("上传文件为空")
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    target_path = VIDEOS_DIR / safe_file_name(filename)
    target_path.write_bytes(content)
    return create_video_from_local_path({"localPath": str(target_path), "title": title or Path(filename).name}, "本地导入")


def rename_video(video_id: str, title: str | None) -> dict[str, Any]:
    videos = read_json(VIDEOS_PATH, [])
    index = next((i for i, video in enumerate(videos) if video.get("id") == video_id), -1)
    if index < 0:
        raise RuntimeError(f"视频不存在：{video_id}")
    videos[index] = {**videos[index], "title": title or videos[index].get("name"), "updatedAt": now_iso()}
    write_json(VIDEOS_PATH, videos)
    return videos[index]


def patch_video(video_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    videos = read_json(VIDEOS_PATH, [])
    index = next((i for i, video in enumerate(videos) if video.get("id") == video_id), -1)
    if index < 0:
        return None
    videos[index] = {**videos[index], **patch, "updatedAt": now_iso()}
    write_json(VIDEOS_PATH, videos)
    return videos[index]


def reprobe_video(video_id: str) -> dict[str, Any]:
    videos = read_json(VIDEOS_PATH, [])
    index = next((i for i, video in enumerate(videos) if video.get("id") == video_id), -1)
    if index < 0:
        raise RuntimeError(f"视频不存在：{video_id}")
    try:
        metadata = probe_video(videos[index].get("localPath"))
        videos[index] = {**videos[index], **metadata, "status": "可用", "metadataError": "", "updatedAt": now_iso()}
    except Exception as error:
        videos[index] = {**videos[index], "status": "待识别", "metadataError": str(error), "updatedAt": now_iso()}
    write_json(VIDEOS_PATH, videos)
    return videos[index]


def video_file_response(video_id: str) -> FileResponse:
    video = get_video(video_id)
    local_path = Path(str(video.get("localPath") or "")).resolve()
    if not local_path.exists():
        raise HTTPException(status_code=404, detail=f"视频文件不存在：{local_path}")
    media_type = mimetypes.guess_type(local_path.name)[0] or "video/mp4"
    return FileResponse(local_path, media_type=media_type, filename=local_path.name)


def is_magnet_url(value: Any) -> bool:
    return str(value or "").strip().lower().startswith("magnet:?")


def parse_file_size(text: str) -> int:
    match = re.search(r"([\d.]+)\s*([kmgtp]?i?b|bytes?)", text.strip(), re.IGNORECASE)
    if not match:
        return 0
    value = float(match.group(1))
    unit = match.group(2).lower()
    multipliers = {
        "byte": 1, "bytes": 1, "b": 1,
        "kb": 1000, "mb": 1000**2, "gb": 1000**3, "tb": 1000**4, "pb": 1000**5,
        "kib": 1024, "mib": 1024**2, "gib": 1024**3, "tib": 1024**4, "pib": 1024**5,
    }
    return int(value * multipliers.get(unit, 1))


def format_bytes(size: int) -> str:
    if size <= 0:
        return "未知"
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    unit_index = 0
    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1
    return f"{value:.1f} {units[unit_index]}"


def parse_aria2_file_list(text: str) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        file_match = re.match(r"\s*(\d+)\|(.+?)\s*$", line)
        if file_match:
            current = {"index": int(file_match.group(1)), "path": file_match.group(2).strip(), "size": 0, "sizeText": "未知"}
            files.append(current)
            continue
        size_match = re.match(r"\s*\|\s*(.+?)\s*$", line)
        if current and size_match:
            size_text = size_match.group(1).strip()
            size = parse_file_size(size_text)
            if size:
                current["size"] = size
                current["sizeText"] = format_bytes(size)
    return [item for item in files if item.get("path")]


def magnet_info_hash(url: str) -> str:
    match = re.search(r"btih:([a-z0-9]{32,40})", url, re.IGNORECASE)
    return match.group(1).lower() if match else safe_file_name(url)[:48]


def tail_text(text: str, max_lines: int = 20) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines[-max_lines:])


def aria2_no_peer_metadata(text: str) -> bool:
    return "[MEMORY][METADATA]" in text and "CN:0" in text and ".torrent" not in text.lower()


def fetch_magnet_torrent(url: str, aria2c_command: str) -> Path:
    metadata_dir = DATA_ROOT / "torrents" / magnet_info_hash(url)
    metadata_dir.mkdir(parents=True, exist_ok=True)
    for old_file in metadata_dir.glob("*.torrent"):
        old_file.unlink(missing_ok=True)
    args = [
        "--bt-metadata-only=true",
        "--bt-save-metadata=true",
        "--bt-stop-timeout=60",
        "--summary-interval=0",
        "--console-log-level=warn",
        "--dir", str(metadata_dir),
        url,
    ]
    try:
        result = subprocess.run(
            [aria2c_command, *args],
            cwd=str(PROJECT_ROOT),
            text=True,
            capture_output=True,
            check=False,
            timeout=65,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("磁力链接元数据加载超时：未能在 60 秒内连接到可用节点")
    torrent_files = sorted(metadata_dir.glob("*.torrent"), key=lambda path: path.stat().st_mtime, reverse=True)
    if torrent_files:
        return torrent_files[0]
    full_output = f"{result.stdout}\n{result.stderr}"
    if aria2_no_peer_metadata(full_output):
        raise RuntimeError("磁力链接元数据加载失败：未连接到可用节点。可以稍后重试，或使用带 tracker 的 magnet / .torrent 文件。")
    detail = tail_text(full_output)
    if result.returncode != 0:
        raise RuntimeError(f"磁力链接元数据加载失败：{detail or f'aria2c 退出码 {result.returncode}'}")
    raise RuntimeError(f"磁力链接元数据未返回文件：{detail or '没有连到可用节点'}")


def list_magnet_files(url: Any) -> list[dict[str, Any]]:
    magnet = str(url or "").strip()
    if not is_magnet_url(magnet):
        raise RuntimeError("请粘贴 magnet:? 开头的磁力链接")
    aria2c_command = resolve_aria2c()
    torrent_path = fetch_magnet_torrent(magnet, aria2c_command)
    args = ["--show-files=true", str(torrent_path)]
    try:
        result = subprocess.run(
            [aria2c_command, *args],
            cwd=str(PROJECT_ROOT),
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("读取种子文件列表超时")
    text = f"{result.stdout}\n{result.stderr}"
    files = parse_aria2_file_list(text)
    if result.returncode != 0 and not files:
        raise RuntimeError(f"磁力链接元数据加载失败：{result.stderr or result.stdout}")
    if not files:
        raise RuntimeError("没有从磁力链接中读取到文件列表")
    return files


def parse_download_progress(text: str) -> dict[str, Any]:
    progress_match = re.search(r"(\d+(?:\.\d+)?)%", text)
    speed_match = re.search(r"\bat\s+([^\s]+/s)", text) or re.search(r"\bDL:([^\]\s]+)", text)
    return {
        "progress": min(99, max(0, float(progress_match.group(1)))) if progress_match else None,
        "speed": speed_match.group(1) if speed_match else "",
    }


def selected_magnet_files(body: dict[str, Any]) -> list[dict[str, Any]]:
    selected_indices = {int(value) for value in body.get("selectedFiles") or [] if str(value).isdigit()}
    details = [item for item in body.get("selectedFileDetails") or [] if int(item.get("index", 0)) in selected_indices]
    if selected_indices and details:
        return details
    return []


def safe_downloaded_path(output_dir: Path, relative_path: Any) -> Path | None:
    if not relative_path:
        return None
    candidate = (output_dir / str(relative_path)).resolve()
    try:
        candidate.relative_to(output_dir.resolve())
    except ValueError:
        return None
    return candidate


def first_existing_downloaded_file(output_dir: Path, selected_files: list[dict[str, Any]]) -> Path | None:
    for selected_file in selected_files:
        candidate = safe_downloaded_path(output_dir, selected_file.get("path"))
        if candidate and candidate.is_file():
            return candidate
    video_extensions = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
    matches = [path for path in output_dir.rglob("*") if path.is_file() and path.suffix.lower() in video_extensions]
    return matches[0] if matches else None


def magnet_download_worker(task: dict[str, Any], video: dict[str, Any], url: str, body: dict[str, Any]) -> None:
    selected_files = selected_magnet_files(body)
    if not selected_files:
        update_task(task["id"], {"status": "失败", "progress": 100, "error": "磁力链接下载前必须选择文件"})
        patch_video(video["id"], {"status": "失败", "downloadProgress": 100, "metadataError": "磁力链接下载前必须选择文件"})
        return

    output_dir = VIDEOS_DIR / safe_file_name(f"{video['id']}_{int(time.time())}")
    output_dir.mkdir(parents=True, exist_ok=True)
    selected_indices = ",".join(str(item["index"]) for item in selected_files)
    args = ["--dir", str(output_dir), "--select-file", selected_indices, "--seed-time=0", "--summary-interval=1", "--console-log-level=notice", url]
    update_task(task["id"], {"status": "运行中", "progress": 5, "log": [f"aria2c {' '.join(args[:-1])} magnet:..."]})
    try:
        child = subprocess.Popen(
            [resolve_aria2c(), *args],
            cwd=str(PROJECT_ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as error:
        update_task(task["id"], {"status": "失败", "progress": 100, "error": f"下载工具启动失败：{error}"})
        patch_video(video["id"], {"status": "失败", "metadataError": f"下载工具启动失败：{error}"})
        return
    register_task_process(task["id"], child)

    def read_output(stream: Any) -> None:
        last_progress = video.get("downloadProgress", 0)
        last_speed = video.get("downloadSpeed", "")
        for line in stream:
            text = line.strip()
            if not text:
                continue
            download = parse_download_progress(text)
            if download["progress"] is not None:
                last_progress = download["progress"]
            if download["speed"]:
                last_speed = download["speed"]
            append_task_log(task["id"], text, last_progress if download["progress"] is not None else None)
            patch_video(video["id"], {"status": "下载中", "downloadProgress": last_progress, "downloadSpeed": last_speed})

    import threading

    threads = []
    for stream in [child.stdout, child.stderr]:
        if stream is not None:
            thread = threading.Thread(target=read_output, args=(stream,), daemon=True)
            thread.start()
            threads.append(thread)
    try:
        code = child.wait()
        for thread in threads:
            thread.join(timeout=1)
    finally:
        unregister_task_process(task["id"])

    if is_cancel_requested(task["id"]):
        mark_cancelled(task["id"])
        patch_video(video["id"], {"status": "已取消", "downloadProgress": 100, "downloadSpeed": "", "metadataError": "下载任务已取消"})
        return

    if code != 0:
        update_task(task["id"], {"status": "失败", "progress": 100, "error": f"下载工具退出码：{code}"})
        patch_video(video["id"], {"status": "失败", "downloadProgress": 100, "metadataError": f"下载工具退出码：{code}"})
        return

    downloaded_path = first_existing_downloaded_file(output_dir, selected_files)
    if not downloaded_path:
        update_task(task["id"], {"status": "失败", "progress": 100, "error": "下载完成但未找到已选择的视频文件"})
        patch_video(video["id"], {"status": "失败", "downloadProgress": 100, "metadataError": "下载完成但未找到已选择的视频文件"})
        return

    metadata = {"duration": 0, "resolution": "待识别", "fps": 0}
    status = "可用"
    metadata_error = ""
    try:
        metadata = probe_video(downloaded_path)
    except Exception as error:
        status = "待识别"
        metadata_error = str(error)
    updated_video = patch_video(video["id"], {"name": downloaded_path.name, "localPath": str(downloaded_path.resolve()), **metadata, "status": status, "metadataError": metadata_error, "downloadProgress": 100, "downloadSpeed": ""})
    update_task(task["id"], {"status": "完成", "progress": 100, "output": {"videoId": video["id"], "localPath": updated_video.get("localPath") if updated_video else str(downloaded_path)}})


def download_worker(task: dict[str, Any], video: dict[str, Any], url: str) -> None:
    output_pattern = str(VIDEOS_DIR / "%(title).200B.%(ext)s")
    args = ["--no-playlist", "--print", "after_move:filepath", "-o", output_pattern, url]
    update_task(task["id"], {"status": "运行中", "progress": 5, "log": [f"yt-dlp {' '.join(args)}"]})
    try:
        child = subprocess.Popen(
            ["yt-dlp", *args],
            cwd=str(PROJECT_ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as error:
        update_task(task["id"], {"status": "失败", "progress": 100, "error": f"下载工具启动失败：{error}"})
        patch_video(video["id"], {"status": "失败", "metadataError": f"下载工具启动失败：{error}"})
        return
    register_task_process(task["id"], child)

    stdout_lines: list[str] = []

    def read_stdout() -> None:
        assert child.stdout is not None
        for line in child.stdout:
            text = line.strip()
            if text:
                stdout_lines.append(text)
                append_task_log(task["id"], text, 70)

    def read_stderr() -> None:
        assert child.stderr is not None
        last_progress = video.get("downloadProgress", 0)
        last_speed = video.get("downloadSpeed", "")
        for line in child.stderr:
            text = line.strip()
            if not text:
                continue
            download = parse_download_progress(text)
            if download["progress"] is not None:
                last_progress = download["progress"]
            if download["speed"]:
                last_speed = download["speed"]
            append_task_log(task["id"], text, last_progress if download["progress"] is not None else None)
            patch_video(video["id"], {"status": "下载中", "downloadProgress": last_progress, "downloadSpeed": last_speed})

    import threading

    stdout_thread = threading.Thread(target=read_stdout, daemon=True)
    stderr_thread = threading.Thread(target=read_stderr, daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    try:
        code = child.wait()
        stdout_thread.join(timeout=1)
        stderr_thread.join(timeout=1)
    finally:
        unregister_task_process(task["id"])

    if is_cancel_requested(task["id"]):
        mark_cancelled(task["id"])
        patch_video(video["id"], {"status": "已取消", "downloadProgress": 100, "downloadSpeed": "", "metadataError": "下载任务已取消"})
        return

    if code != 0:
        update_task(task["id"], {"status": "失败", "progress": 100, "error": f"下载工具退出码：{code}"})
        patch_video(video["id"], {"status": "失败", "downloadProgress": 100, "metadataError": f"下载工具退出码：{code}"})
        return

    downloaded_path = next((line for line in reversed(stdout_lines) if line), "")
    if not downloaded_path:
        update_task(task["id"], {"status": "失败", "progress": 100, "error": "下载完成但未返回文件路径"})
        patch_video(video["id"], {"status": "失败", "downloadProgress": 100, "metadataError": "下载完成但未返回文件路径"})
        return

    metadata = {"duration": 0, "resolution": "待识别", "fps": 0}
    status = "可用"
    metadata_error = ""
    try:
        metadata = probe_video(downloaded_path)
    except Exception as error:
        status = "待识别"
        metadata_error = str(error)
    updated_video = patch_video(video["id"], {"name": Path(downloaded_path).name, "localPath": str(Path(downloaded_path).resolve()), **metadata, "status": status, "metadataError": metadata_error, "downloadProgress": 100, "downloadSpeed": ""})
    update_task(task["id"], {"status": "完成", "progress": 100, "output": {"videoId": video["id"], "localPath": updated_video.get("localPath") if updated_video else downloaded_path}})


def start_video_download(body: dict[str, Any]) -> dict[str, Any]:
    if not body.get("url"):
        raise RuntimeError("必须提供下载地址")
    if is_magnet_url(body.get("url")) and not body.get("selectedFiles"):
        raise RuntimeError("磁力链接必须先加载文件列表并选择要下载的内容")
    videos = read_json(VIDEOS_PATH, [])
    parsed_name = Path(urlparse(str(body["url"])).path).name
    selected_details = selected_magnet_files(body)
    selected_name = Path(str(selected_details[0].get("path"))).name if selected_details else ""
    title = body.get("title") or parsed_name or selected_name or "下载视频"
    video = {
        "id": unique_id(title, "video", videos),
        "title": title,
        "name": title,
        "source": "下载",
        "url": body["url"],
        "localPath": "",
        "duration": 0,
        "resolution": "下载中",
        "fps": 0,
        "status": "下载中",
        "downloadProgress": 0,
        "downloadSpeed": "",
        "downloadFiles": selected_details,
        "metadataError": "",
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
    }
    videos.insert(0, video)
    write_json(VIDEOS_PATH, videos)
    task = create_task("下载视频", str(body["url"]), {**body, "videoId": video["id"]})
    if is_magnet_url(body.get("url")):
        start_thread(magnet_download_worker, task, video, str(body["url"]), body)
    else:
        start_thread(download_worker, task, video, str(body["url"]))
    return task
