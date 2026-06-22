#!/usr/bin/env python3
"""Coarsely classify extracted frames with lightweight image metrics."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path
from statistics import mean, pstdev


REJECT_LABELS = {
    "black_or_near_black",
    "white_or_flash",
    "blurry_motion",
    "duplicate_or_near_duplicate",
    "subtitle_heavy",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score raw extracted frames and write manifests/frames_scored.jsonl.")
    parser.add_argument("--source-dir", required=True, type=Path, help="Source directory containing frames_raw/ and manifests/.")
    parser.add_argument("--input-manifest", type=Path, help="Input JSONL manifest. Default: <source-dir>/manifests/frames_raw.jsonl.")
    parser.add_argument("--output-manifest", type=Path, help="Output JSONL manifest. Default: <source-dir>/manifests/frames_scored.jsonl.")
    parser.add_argument("--sample-size", type=int, default=64, help="Square grayscale sample size for metrics. Default: 64.")
    parser.add_argument("--black-mean", type=float, default=18.0, help="Mean luma threshold for near-black frames.")
    parser.add_argument("--black-std", type=float, default=12.0, help="Stddev luma threshold for near-black frames.")
    parser.add_argument("--white-mean", type=float, default=238.0, help="Mean luma threshold for flash/white frames.")
    parser.add_argument("--blur-edge", type=float, default=4.5, help="Mean adjacent-pixel gradient threshold for blur.")
    parser.add_argument("--subtitle-contrast", type=float, default=58.0, help="Bottom-band stddev threshold for likely subtitles.")
    parser.add_argument("--duplicate-hamming", type=int, default=4, help="aHash hamming distance for near-duplicate frames.")
    parser.add_argument("--copy-files", action="store_true", help="Copy selected/rejected frames into frames_selected/ and frames_rejected/<reason>/.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing output manifest.")
    return parser.parse_args()


def require_binary(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"Required executable not found on PATH: {name}")


def read_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as input_file:
        for line_number, line in enumerate(input_file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rows.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
    return rows


def write_jsonl(path: Path, rows: list[dict[str, object]], overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Output manifest already exists, pass --overwrite to replace it: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as output_file:
        for row in rows:
            output_file.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def resolve_data_path(value: object, source_dir: Path) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"Expected non-empty path string, got: {value!r}")
    path = Path(value)
    if path.is_absolute():
        return path

    candidates = [source_dir.parent / path, source_dir / path]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def relative_to_dataset(path: Path, source_dir: Path) -> str:
    try:
        return path.resolve().relative_to(source_dir.parent.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def decode_grayscale(frame_path: Path, sample_size: int) -> list[int]:
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(frame_path),
        "-vf",
        f"scale={sample_size}:{sample_size},format=gray",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "-",
    ]
    result = subprocess.run(command, check=True, capture_output=True)
    expected = sample_size * sample_size
    if len(result.stdout) != expected:
        raise RuntimeError(f"Unexpected decoded byte count for {frame_path}: {len(result.stdout)} != {expected}")
    return list(result.stdout)


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


def hamming(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def bottom_band_std(pixels: list[int], size: int) -> float:
    start_y = math.floor(size * 0.72)
    band = pixels[start_y * size :]
    return pstdev(band) if len(band) > 1 else 0.0


def classify_metrics(
    pixels: list[int],
    size: int,
    args: argparse.Namespace,
    seen_hashes: list[int],
) -> tuple[list[str], dict[str, float | int | bool | None], str | None]:
    luma_mean = mean(pixels)
    luma_std = pstdev(pixels)
    edge = edge_score(pixels, size)
    bottom_std = bottom_band_std(pixels, size)
    frame_hash = ahash(pixels, size)
    min_hamming = min((hamming(frame_hash, seen_hash) for seen_hash in seen_hashes), default=None)

    labels: list[str] = []
    reject_reason: str | None = None

    if luma_mean <= args.black_mean and luma_std <= args.black_std:
        labels.append("black_or_near_black")
    if luma_mean >= args.white_mean and luma_std <= args.black_std:
        labels.append("white_or_flash")
    if edge <= args.blur_edge and "black_or_near_black" not in labels and "white_or_flash" not in labels:
        labels.append("blurry_motion")
    if bottom_std >= args.subtitle_contrast and luma_std >= 35:
        labels.append("subtitle_heavy")
    if min_hamming is not None and min_hamming <= args.duplicate_hamming:
        labels.append("duplicate_or_near_duplicate")

    for label in labels:
        if label in REJECT_LABELS:
            reject_reason = label
            break

    if not labels:
        labels.append("usable_style_candidate")

    metrics = {
        "luma_mean": round(luma_mean, 3),
        "luma_std": round(luma_std, 3),
        "edge_score": round(edge, 3),
        "bottom_band_std": round(bottom_std, 3),
        "ahash": f"{frame_hash:016x}",
        "nearest_duplicate_hamming": min_hamming,
    }
    return labels, metrics, reject_reason


def quality_score(labels: list[str], metrics: dict[str, float | int | bool | None]) -> float:
    score = 100.0
    penalties = {
        "black_or_near_black": 100.0,
        "white_or_flash": 90.0,
        "blurry_motion": 45.0,
        "duplicate_or_near_duplicate": 60.0,
        "subtitle_heavy": 35.0,
    }
    for label in labels:
        score -= penalties.get(label, 0.0)
    if isinstance(metrics.get("edge_score"), float):
        score += min(metrics["edge_score"] / 3.0, 8.0)  # type: ignore[operator]
    return round(max(0.0, min(100.0, score)), 3)


def copy_frame(frame_path: Path, source_dir: Path, labels: list[str], reject_reason: str | None) -> str:
    if reject_reason:
        target_dir = source_dir / "frames_rejected" / reject_reason
    else:
        target_dir = source_dir / "frames_selected"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / frame_path.name
    shutil.copy2(frame_path, target_path)
    return relative_to_dataset(target_path, source_dir)


def main() -> int:
    args = parse_args()
    if args.sample_size < 8:
        raise ValueError("--sample-size must be at least 8")

    require_binary("ffmpeg")
    source_dir = args.source_dir.resolve()
    input_manifest = args.input_manifest or source_dir / "manifests" / "frames_raw.jsonl"
    output_manifest = args.output_manifest or source_dir / "manifests" / "frames_scored.jsonl"

    rows = read_jsonl(input_manifest.resolve())
    scored_rows: list[dict[str, object]] = []
    seen_hashes: list[int] = []

    for row in rows:
        frame_path = resolve_data_path(row.get("frame_path"), source_dir)
        if not frame_path.is_file():
            raise FileNotFoundError(f"Frame not found: {frame_path}")

        pixels = decode_grayscale(frame_path, args.sample_size)
        labels, metrics, reject_reason = classify_metrics(pixels, args.sample_size, args, seen_hashes)
        seen_hashes.append(int(str(metrics["ahash"]), 16))
        include_in_training = reject_reason is None

        output_row = dict(row)
        output_row.update(
            {
                "classification_labels": labels,
                "quality_metrics": metrics,
                "quality_score": quality_score(labels, metrics),
                "include_in_training": include_in_training,
                "reject_reason": reject_reason,
                "script_version": "classify_frames.py/0.1",
            }
        )
        if args.copy_files:
            output_row["classified_frame_path"] = copy_frame(frame_path, source_dir, labels, reject_reason)
        scored_rows.append(output_row)

    write_jsonl(output_manifest.resolve(), scored_rows, args.overwrite)
    selected = sum(1 for row in scored_rows if row["include_in_training"])
    rejected = len(scored_rows) - selected
    print(f"Scored {len(scored_rows)} frames")
    print(f"Selected: {selected}")
    print(f"Rejected: {rejected}")
    print(f"Manifest: {output_manifest.resolve()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)