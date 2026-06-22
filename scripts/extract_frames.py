#!/usr/bin/env python3
"""Extract raw candidate frames from a video and write a JSONL manifest."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class VideoInfo:
    width: int | None
    height: int | None
    duration_sec: float | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract still frames from a video and create manifests/frames_raw.jsonl."
    )
    parser.add_argument("--video", required=True, type=Path, help="Input video file path.")
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Source output directory. The script creates frames_raw/ and manifests/ inside it.",
    )
    parser.add_argument(
        "--interval-sec",
        type=float,
        default=5.0,
        help="Seconds between extracted frames. Default: 5.0.",
    )
    parser.add_argument(
        "--source-id",
        help="Stable source id used in filenames and manifest. Defaults to the video stem.",
    )
    parser.add_argument(
        "--start-sec",
        type=float,
        default=0.0,
        help="Start timestamp in seconds. Default: 0.0.",
    )
    parser.add_argument(
        "--end-sec",
        type=float,
        help="End timestamp in seconds. Defaults to the video duration when ffprobe can read it.",
    )
    parser.add_argument(
        "--jpg-quality",
        type=int,
        default=2,
        help="ffmpeg JPEG q:v value, 2 is high quality and 31 is low quality. Default: 2.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing frame files and manifest.",
    )
    return parser.parse_args()


def require_binary(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"Required executable not found on PATH: {name}")


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True)


def probe_video(video_path: Path) -> VideoInfo:
    result = run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,duration:format=duration",
            "-of",
            "json",
            str(video_path),
        ]
    )
    payload = json.loads(result.stdout)
    stream = (payload.get("streams") or [{}])[0]
    file_format = payload.get("format") or {}
    duration = stream.get("duration") or file_format.get("duration")

    return VideoInfo(
        width=int(stream["width"]) if stream.get("width") is not None else None,
        height=int(stream["height"]) if stream.get("height") is not None else None,
        duration_sec=float(duration) if duration is not None else None,
    )


def iter_timestamps(start_sec: float, end_sec: float, interval_sec: float) -> Iterable[float]:
    timestamp = start_sec
    epsilon = min(0.001, interval_sec / 1000.0)
    while timestamp <= end_sec + epsilon:
        yield round(timestamp, 2)
        timestamp += interval_sec


def make_relative(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def extract_frame(
    video_path: Path,
    frame_path: Path,
    timestamp_sec: float,
    jpg_quality: int,
    overwrite: bool,
) -> None:
    if frame_path.exists() and not overwrite:
        return

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
    ]
    if overwrite:
        command.append("-y")
    else:
        command.append("-n")

    command.extend(
        [
            "-ss",
            f"{timestamp_sec:.2f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            str(jpg_quality),
            str(frame_path),
        ]
    )
    run_command(command)


def write_manifest_row(manifest_file, row: dict[str, object]) -> None:
    manifest_file.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> int:
    args = parse_args()

    if args.interval_sec <= 0:
        raise ValueError("--interval-sec must be greater than 0")
    if args.start_sec < 0:
        raise ValueError("--start-sec must be greater than or equal to 0")
    if not 2 <= args.jpg_quality <= 31:
        raise ValueError("--jpg-quality must be between 2 and 31 for ffmpeg q:v")

    video_path = args.video.resolve()
    output_dir = args.output_dir.resolve()
    if not video_path.is_file():
        raise FileNotFoundError(f"Input video does not exist: {video_path}")

    require_binary("ffmpeg")
    require_binary("ffprobe")

    video_info = probe_video(video_path)
    if args.end_sec is None and video_info.duration_sec is None:
        raise ValueError("Could not determine video duration; pass --end-sec explicitly.")

    end_sec = args.end_sec if args.end_sec is not None else video_info.duration_sec
    assert end_sec is not None
    if end_sec < args.start_sec:
        raise ValueError("--end-sec must be greater than or equal to --start-sec")

    source_id = args.source_id or video_path.stem
    frames_dir = output_dir / "frames_raw"
    manifests_dir = output_dir / "manifests"
    manifest_path = manifests_dir / "frames_raw.jsonl"
    frames_dir.mkdir(parents=True, exist_ok=True)
    manifests_dir.mkdir(parents=True, exist_ok=True)

    if manifest_path.exists() and not args.overwrite:
        raise FileExistsError(f"Manifest already exists, pass --overwrite to replace it: {manifest_path}")

    frame_count = 0
    dataset_root = output_dir.parent
    with manifest_path.open("w", encoding="utf-8") as manifest_file:
        for timestamp_sec in iter_timestamps(args.start_sec, end_sec, args.interval_sec):
            frame_name = f"{source_id}_t{timestamp_sec:09.2f}.jpg"
            frame_path = frames_dir / frame_name
            extract_frame(video_path, frame_path, timestamp_sec, args.jpg_quality, args.overwrite)

            if not frame_path.is_file():
                raise RuntimeError(f"Frame was not created: {frame_path}")

            row = {
                "source_id": source_id,
                "video_path": make_relative(video_path, dataset_root),
                "frame_path": make_relative(frame_path, dataset_root),
                "timestamp_sec": timestamp_sec,
                "extract_interval_sec": args.interval_sec,
                "width": video_info.width,
                "height": video_info.height,
            }
            write_manifest_row(manifest_file, row)
            frame_count += 1

    print(f"Extracted {frame_count} frames")
    print(f"Frames: {frames_dir}")
    print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)