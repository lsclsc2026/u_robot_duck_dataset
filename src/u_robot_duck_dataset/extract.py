"""Extract compressed camera payloads from ROS 2 bags without re-encoding."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml

from .session import load_metadata, now_iso, save_metadata


def _storage_identifier(bag_dir: Path) -> str:
    metadata_path = bag_dir / "metadata.yaml"
    if metadata_path.is_file():
        with metadata_path.open("r", encoding="utf-8") as stream:
            payload = yaml.safe_load(stream) or {}
        information = payload.get("rosbag2_bagfile_information", {})
        identifier = information.get("storage_identifier")
        if identifier:
            return str(identifier)
    if list(bag_dir.glob("*.mcap")):
        return "mcap"
    return "sqlite3"


def _message_header_timestamp_ns(message: Any) -> int | None:
    header = getattr(message, "header", None)
    stamp = getattr(header, "stamp", None)
    if stamp is None:
        return None
    value = int(stamp.sec) * 1_000_000_000 + int(stamp.nanosec)
    return value if value > 0 else None


def _image_extension(format_name: str, payload: bytes) -> str:
    normalized = format_name.lower()
    if "jpeg" in normalized or "jpg" in normalized or payload.startswith(b"\xff\xd8"):
        return ".jpg"
    if "png" in normalized or payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    raise ValueError(f"unsupported compressed image format: {format_name!r}")


def _decode_dimensions(payload: bytes) -> tuple[int, int]:
    encoded = np.frombuffer(payload, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("compressed image payload cannot be decoded")
    height, width = image.shape[:2]
    return width, height


def _safe_remove_frames(frames_dir: Path, session_dir: Path) -> None:
    if frames_dir.resolve().parent != session_dir.resolve() or frames_dir.name != "frames":
        raise ValueError(f"refusing to remove unexpected frames path: {frames_dir}")
    if frames_dir.exists():
        shutil.rmtree(frames_dir)


def extract_frames(
    *,
    session_dir: Path,
    bag_dir: Path | None = None,
    topic: str | None = None,
    sample_fps: float = 0.0,
    start_sec: float = 0.0,
    end_sec: float | None = None,
    max_frames: int | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    if sample_fps < 0:
        raise ValueError("sample FPS must be non-negative")
    if start_sec < 0 or (end_sec is not None and end_sec <= start_sec):
        raise ValueError("invalid extraction time range")
    if max_frames is not None and max_frames <= 0:
        raise ValueError("max frames must be positive")

    try:
        import rosbag2_py
        from rclpy.serialization import deserialize_message
        from rosidl_runtime_py.utilities import get_message
    except ImportError as error:
        raise RuntimeError(
            "ROS 2 Python modules are unavailable; source /opt/ros/humble/setup.bash"
        ) from error

    session_dir = session_dir.expanduser().resolve()
    metadata = load_metadata(session_dir)
    selected_topic = topic or metadata["camera"]["topic"]
    configured_bag = metadata.get("paths", {}).get("bag")
    if bag_dir is None:
        if not configured_bag:
            raise ValueError("session metadata does not contain a recorded bag path")
        bag_dir = session_dir / configured_bag
    bag_dir = bag_dir.expanduser().resolve()
    if not (bag_dir / "metadata.yaml").is_file():
        raise FileNotFoundError(f"ROS bag metadata not found: {bag_dir}")

    frames_dir = session_dir / "frames"
    existing_outputs = frames_dir.exists() and any(frames_dir.iterdir())
    if existing_outputs and not overwrite:
        raise FileExistsError(
            f"frames already exist in {frames_dir}; pass --overwrite to replace them"
        )

    reader = rosbag2_py.SequentialReader()
    reader.open(
        rosbag2_py.StorageOptions(
            uri=str(bag_dir), storage_id=_storage_identifier(bag_dir)
        ),
        rosbag2_py.ConverterOptions(
            input_serialization_format="", output_serialization_format=""
        ),
    )
    type_by_topic = {
        item.name: item.type for item in reader.get_all_topics_and_types()
    }
    if selected_topic not in type_by_topic:
        available = ", ".join(sorted(type_by_topic)) or "none"
        raise ValueError(
            f"topic {selected_topic!r} is absent from bag; available topics: {available}"
        )
    message_type_name = type_by_topic[selected_topic]
    if message_type_name != "sensor_msgs/msg/CompressedImage":
        raise TypeError(
            f"topic {selected_topic!r} has type {message_type_name}, expected "
            "sensor_msgs/msg/CompressedImage"
        )
    message_type = get_message(message_type_name)

    staging_dir = Path(
        tempfile.mkdtemp(prefix=".frames-extract-", dir=str(session_dir))
    )
    manifest_path = staging_dir / "frames.jsonl"
    first_topic_timestamp: int | None = None
    last_selected_timestamp: int | None = None
    minimum_interval_ns = int(1_000_000_000 / sample_fps) if sample_fps else 0
    total_topic_messages = 0
    extracted = 0
    duplicate_frames = 0
    first_hash_index: dict[str, int] = {}
    first_output_timestamp: int | None = None
    last_output_timestamp: int | None = None
    dimensions: set[tuple[int, int]] = set()

    try:
        with manifest_path.open("w", encoding="utf-8") as manifest:
            while reader.has_next():
                read_topic, serialized, bag_timestamp_ns = reader.read_next()
                if read_topic != selected_topic:
                    continue
                total_topic_messages += 1
                bag_timestamp_ns = int(bag_timestamp_ns)
                if first_topic_timestamp is None:
                    first_topic_timestamp = bag_timestamp_ns
                relative_sec = (
                    bag_timestamp_ns - first_topic_timestamp
                ) / 1_000_000_000
                if relative_sec < start_sec:
                    continue
                if end_sec is not None and relative_sec > end_sec:
                    break
                if (
                    last_selected_timestamp is not None
                    and minimum_interval_ns
                    and bag_timestamp_ns - last_selected_timestamp < minimum_interval_ns
                ):
                    continue

                message = deserialize_message(serialized, message_type)
                compressed = bytes(message.data)
                extension = _image_extension(str(message.format), compressed)
                width, height = _decode_dimensions(compressed)
                dimensions.add((width, height))
                digest = hashlib.sha256(compressed).hexdigest()
                duplicate_of = first_hash_index.get(digest)
                if duplicate_of is None:
                    first_hash_index[digest] = extracted
                else:
                    duplicate_frames += 1

                filename = f"{extracted:06d}{extension}"
                (staging_dir / filename).write_bytes(compressed)
                header_timestamp_ns = _message_header_timestamp_ns(message)
                record = {
                    "index": extracted,
                    "filename": filename,
                    "topic": selected_topic,
                    "bag_timestamp_ns": bag_timestamp_ns,
                    "header_timestamp_ns": header_timestamp_ns,
                    "relative_sec": relative_sec,
                    "format": str(message.format),
                    "width": width,
                    "height": height,
                    "payload_bytes": len(compressed),
                    "sha256": digest,
                    "duplicate_of": duplicate_of,
                }
                manifest.write(json.dumps(record, ensure_ascii=False) + "\n")
                last_selected_timestamp = bag_timestamp_ns
                first_output_timestamp = first_output_timestamp or bag_timestamp_ns
                last_output_timestamp = bag_timestamp_ns
                extracted += 1
                if max_frames is not None and extracted >= max_frames:
                    break

        if extracted == 0:
            raise ValueError("no frames matched the extraction settings")

        if overwrite:
            _safe_remove_frames(frames_dir, session_dir)
        elif frames_dir.exists():
            frames_dir.rmdir()
        os.replace(staging_dir, frames_dir)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    duration_sec = (
        (last_output_timestamp - first_output_timestamp) / 1_000_000_000
        if extracted > 1 and first_output_timestamp is not None
        else 0.0
    )
    estimated_fps = (extracted - 1) / duration_sec if duration_sec > 0 else None
    summary: dict[str, Any] = {
        "schema_version": 1,
        "created_at": now_iso(),
        "session_id": metadata["session_id"],
        "bag": str(bag_dir),
        "topic": selected_topic,
        "storage_identifier": _storage_identifier(bag_dir),
        "total_topic_messages_seen": total_topic_messages,
        "extracted_frames": extracted,
        "duplicate_frames": duplicate_frames,
        "duration_sec": duration_sec,
        "estimated_fps": estimated_fps,
        "dimensions": [
            {"width": width, "height": height} for width, height in sorted(dimensions)
        ],
        "preserved_compressed_payload": True,
        "selection": {
            "sample_fps": sample_fps,
            "start_sec": start_sec,
            "end_sec": end_sec,
            "max_frames": max_frames,
        },
    }
    summary_path = session_dir / "artifacts" / "extraction_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    metadata["status"] = "extracted"
    metadata["extraction"] = {
        "completed_at": now_iso(),
        "frame_count": extracted,
        "duplicate_frames": duplicate_frames,
        "estimated_fps": estimated_fps,
        "preserved_compressed_payload": True,
    }
    save_metadata(session_dir, metadata)
    return summary

