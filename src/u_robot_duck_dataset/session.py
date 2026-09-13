"""Session metadata and directory layout."""

from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


DEFAULT_DATA_ROOT = Path(
    os.environ.get(
        "U_ROBOT_DUCK_DATA_ROOT", str(Path.home() / "data" / "duck_dataset")
    )
)
DEFAULT_TOPIC = "/camera/front/image/compressed"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower()).strip("-")
    return slug or "scene"


def make_session_id(scene: str) -> str:
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    return f"{timestamp}_{_slug(scene)}"


def validate_session_id(session_id: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", session_id):
        raise ValueError(
            "session ID may contain only letters, digits, underscore, and hyphen"
        )
    return session_id


def parse_presence(value: str) -> bool | None:
    normalized = value.strip().lower()
    if normalized in {"true", "yes", "1"}:
        return True
    if normalized in {"false", "no", "0"}:
        return False
    if normalized in {"unknown", "unset", "none"}:
        return None
    raise ValueError("duck presence must be true, false, or unknown")


def atomic_write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent, text=True
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            yaml.safe_dump(
                payload,
                stream,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            )
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def load_metadata(session_dir: Path) -> dict[str, Any]:
    metadata_path = session_dir / "session.yaml"
    if not metadata_path.is_file():
        raise FileNotFoundError(f"missing session metadata: {metadata_path}")
    with metadata_path.open("r", encoding="utf-8") as stream:
        payload = yaml.safe_load(stream)
    if not isinstance(payload, dict):
        raise ValueError(f"invalid session metadata: {metadata_path}")
    return payload


def save_metadata(session_dir: Path, payload: dict[str, Any]) -> None:
    payload["updated_at"] = now_iso()
    atomic_write_yaml(session_dir / "session.yaml", payload)


def create_session(
    *,
    root: Path,
    scene: str,
    duck_present: bool | None,
    duck_count: int | None,
    lighting: str,
    distance_range: str,
    occlusion: str,
    notes: str,
    topic: str,
    session_id: str | None = None,
) -> Path:
    if not scene.strip():
        raise ValueError("scene must not be empty")
    if duck_count is not None and duck_count < 0:
        raise ValueError("duck count must be non-negative")
    if duck_present is False and duck_count not in {None, 0}:
        raise ValueError("duck count must be zero when duck-present is false")
    if duck_present is True and duck_count == 0:
        raise ValueError("duck count cannot be zero when duck-present is true")
    if not topic.startswith("/"):
        raise ValueError("camera topic must be an absolute ROS topic")

    identifier = validate_session_id(session_id or make_session_id(scene))
    session_dir = root.expanduser().resolve() / "sessions" / identifier
    try:
        session_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise FileExistsError(f"session already exists: {session_dir}") from error

    for name in ("raw", "frames", "artifacts", "logs"):
        (session_dir / name).mkdir()

    payload: dict[str, Any] = {
        "schema_version": 1,
        "session_id": identifier,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "status": "initialized",
        "scene": scene.strip(),
        "duck": {"present": duck_present, "count": duck_count},
        "conditions": {
            "lighting": lighting.strip() or "unknown",
            "distance_range": distance_range.strip() or "unknown",
            "occlusion": occlusion.strip() or "unknown",
        },
        "camera": {
            "topic": topic,
            "message_type": "sensor_msgs/msg/CompressedImage",
            "expected_format": "jpeg",
            "expected_width": 960,
            "expected_height": 540,
            "nominal_fps": 15.0,
        },
        "paths": {
            "bag": None,
            "frames": "frames",
            "manifest": "frames/frames.jsonl",
            "artifacts": "artifacts",
        },
        "notes": notes.strip(),
    }
    atomic_write_yaml(session_dir / "session.yaml", payload)
    return session_dir


def mark_recorded(session_dir: Path, bag_dir: Path) -> None:
    session_dir = session_dir.expanduser().resolve()
    bag_dir = bag_dir.expanduser().resolve()
    if not bag_dir.is_dir() or not (bag_dir / "metadata.yaml").is_file():
        raise FileNotFoundError(f"not a completed ROS bag directory: {bag_dir}")
    try:
        relative_bag = bag_dir.relative_to(session_dir)
    except ValueError as error:
        raise ValueError("bag directory must be inside the session directory") from error

    payload = load_metadata(session_dir)
    payload["status"] = "recorded"
    payload["paths"]["bag"] = relative_bag.as_posix()
    payload["recording"] = {
        "completed_at": now_iso(),
        "status": "ok",
        "failure_reason": None,
    }
    save_metadata(session_dir, payload)


def mark_recording(session_dir: Path, bag_dir: Path) -> None:
    session_dir = session_dir.expanduser().resolve()
    bag_dir = bag_dir.expanduser().resolve()
    try:
        relative_bag = bag_dir.relative_to(session_dir)
    except ValueError as error:
        raise ValueError("bag directory must be inside the session directory") from error
    payload = load_metadata(session_dir)
    payload["status"] = "recording"
    payload["paths"]["bag"] = relative_bag.as_posix()
    payload["recording"] = {
        "started_at": now_iso(),
        "completed_at": None,
        "status": "active",
        "failure_reason": None,
    }
    save_metadata(session_dir, payload)


def mark_record_failed(session_dir: Path, reason: str) -> None:
    session_dir = session_dir.expanduser().resolve()
    payload = load_metadata(session_dir)
    payload["status"] = "record_failed"
    payload["recording"] = {
        "completed_at": now_iso(),
        "status": "error",
        "failure_reason": reason.strip() or "unknown recording failure",
    }
    save_metadata(session_dir, payload)
