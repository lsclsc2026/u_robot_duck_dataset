"""Validate extracted frames and their provenance manifest."""

from __future__ import annotations

import hashlib
import json
import statistics
from pathlib import Path
from typing import Any

import cv2

from .session import load_metadata, now_iso, save_metadata


def load_manifest(session_dir: Path) -> list[dict[str, Any]]:
    manifest_path = session_dir / "frames" / "frames.jsonl"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"missing frame manifest: {manifest_path}")
    records: list[dict[str, Any]] = []
    with manifest_path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"invalid JSON at {manifest_path}:{line_number}: {error}"
                ) from error
            if not isinstance(record, dict):
                raise ValueError(
                    f"manifest entry at line {line_number} is not an object"
                )
            records.append(record)
    return records


def validate_session(
    *, session_dir: Path, verify_hashes: bool = True
) -> dict[str, Any]:
    session_dir = session_dir.expanduser().resolve()
    metadata = load_metadata(session_dir)
    records = load_manifest(session_dir)
    errors: list[str] = []
    warnings: list[str] = []
    dimensions: set[tuple[int, int]] = set()
    timestamps: list[int] = []
    duplicate_count = 0

    if not records:
        errors.append("manifest contains no frames")

    for expected_index, record in enumerate(records):
        index = record.get("index")
        filename = record.get("filename")
        if index != expected_index:
            errors.append(
                f"manifest index {index!r} is not sequential at position {expected_index}"
            )
        if not isinstance(filename, str) or not filename:
            errors.append(f"frame {expected_index} has no valid filename")
            continue
        frame_path = session_dir / "frames" / filename
        if not frame_path.is_file():
            errors.append(f"missing frame file: {filename}")
            continue
        image = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
        if image is None:
            errors.append(f"cannot decode frame: {filename}")
            continue
        height, width = image.shape[:2]
        dimensions.add((width, height))
        if width != record.get("width") or height != record.get("height"):
            errors.append(f"dimension mismatch for frame: {filename}")
        if verify_hashes:
            digest = hashlib.sha256(frame_path.read_bytes()).hexdigest()
            if digest != record.get("sha256"):
                errors.append(f"SHA256 mismatch for frame: {filename}")
        timestamp = record.get("bag_timestamp_ns")
        if isinstance(timestamp, int):
            timestamps.append(timestamp)
        else:
            errors.append(f"invalid bag timestamp for frame: {filename}")
        if record.get("duplicate_of") is not None:
            duplicate_count += 1

    if any(current <= previous for previous, current in zip(timestamps, timestamps[1:])):
        errors.append("bag timestamps are not strictly increasing")
    if len(dimensions) > 1:
        errors.append(f"frames contain inconsistent dimensions: {sorted(dimensions)}")

    expected_width = metadata.get("camera", {}).get("expected_width")
    expected_height = metadata.get("camera", {}).get("expected_height")
    if dimensions and (expected_width, expected_height) not in dimensions:
        warnings.append(
            "frame dimensions do not match the configured camera profile: "
            f"expected {expected_width}x{expected_height}, got {sorted(dimensions)}"
        )
    if metadata.get("duck", {}).get("present") is None:
        warnings.append(
            "duck presence is unknown; this session must not produce automatic negatives"
        )
    if records and duplicate_count / len(records) > 0.05:
        warnings.append(
            f"{duplicate_count}/{len(records)} frames have identical compressed payloads"
        )

    deltas = [
        (current - previous) / 1_000_000_000
        for previous, current in zip(timestamps, timestamps[1:])
        if current > previous
    ]
    estimated_fps = 1.0 / statistics.median(deltas) if deltas else None
    duration_sec = (
        (timestamps[-1] - timestamps[0]) / 1_000_000_000
        if len(timestamps) > 1
        else 0.0
    )
    report: dict[str, Any] = {
        "schema_version": 1,
        "created_at": now_iso(),
        "session_id": metadata.get("session_id"),
        "status": "ok" if not errors else "error",
        "frame_count": len(records),
        "duration_sec": duration_sec,
        "estimated_fps": estimated_fps,
        "dimensions": [
            {"width": width, "height": height} for width, height in sorted(dimensions)
        ],
        "duplicate_frames": duplicate_count,
        "hashes_verified": verify_hashes,
        "errors": errors,
        "warnings": warnings,
    }
    report_path = session_dir / "artifacts" / "validation_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    metadata["validation"] = {
        "completed_at": now_iso(),
        "status": report["status"],
        "errors": len(errors),
        "warnings": len(warnings),
    }
    if not errors:
        metadata["status"] = "validated"
    save_metadata(session_dir, metadata)
    return report

