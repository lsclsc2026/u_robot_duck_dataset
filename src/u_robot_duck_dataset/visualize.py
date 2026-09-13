"""Create contact-sheet and video previews for an extracted session."""

from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .session import load_metadata, now_iso
from .validate import load_manifest


def _sample_indices(frame_count: int, sample_count: int) -> list[int]:
    if frame_count <= 0 or sample_count <= 0:
        return []
    if sample_count >= frame_count:
        return list(range(frame_count))
    if sample_count == 1:
        return [frame_count // 2]
    return sorted(
        {
            round(index * (frame_count - 1) / (sample_count - 1))
            for index in range(sample_count)
        }
    )


def _letterbox(image: np.ndarray, width: int, height: int) -> np.ndarray:
    source_height, source_width = image.shape[:2]
    scale = min(width / source_width, height / source_height)
    resized_width = max(1, round(source_width * scale))
    resized_height = max(1, round(source_height * scale))
    resized = cv2.resize(
        image, (resized_width, resized_height), interpolation=cv2.INTER_AREA
    )
    canvas = np.full((height, width, 3), 28, dtype=np.uint8)
    x = (width - resized_width) // 2
    y = (height - resized_height) // 2
    canvas[y : y + resized_height, x : x + resized_width] = resized
    return canvas


def _load_frame(session_dir: Path, record: dict[str, Any]) -> np.ndarray:
    frame_path = session_dir / "frames" / str(record["filename"])
    image = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"cannot decode frame: {frame_path}")
    return image


def _estimated_fps(records: list[dict[str, Any]]) -> float:
    if len(records) < 2:
        return 1.0
    duration = (
        int(records[-1]["bag_timestamp_ns"])
        - int(records[0]["bag_timestamp_ns"])
    ) / 1_000_000_000
    if duration <= 0:
        return 1.0
    return min(60.0, max(1.0, (len(records) - 1) / duration))


def create_visualization(
    *,
    session_dir: Path,
    sample_count: int = 24,
    columns: int = 4,
    thumbnail_width: int = 320,
    thumbnail_height: int = 180,
    preview_fps: float = 0.0,
    create_video: bool = True,
) -> dict[str, Any]:
    if sample_count <= 0 or columns <= 0:
        raise ValueError("sample count and columns must be positive")
    if thumbnail_width <= 0 or thumbnail_height <= 0:
        raise ValueError("thumbnail dimensions must be positive")
    if preview_fps < 0:
        raise ValueError("preview FPS must be non-negative")

    session_dir = session_dir.expanduser().resolve()
    metadata = load_metadata(session_dir)
    records = load_manifest(session_dir)
    if not records:
        raise ValueError("cannot visualize a session without frames")
    artifacts_dir = session_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    label_height = 32
    sampled_indices = _sample_indices(len(records), sample_count)
    rows = math.ceil(len(sampled_indices) / columns)
    sheet = np.full(
        (rows * (thumbnail_height + label_height), columns * thumbnail_width, 3),
        245,
        dtype=np.uint8,
    )
    for position, frame_index in enumerate(sampled_indices):
        record = records[frame_index]
        image = _letterbox(
            _load_frame(session_dir, record), thumbnail_width, thumbnail_height
        )
        row, column = divmod(position, columns)
        y = row * (thumbnail_height + label_height)
        x = column * thumbnail_width
        sheet[y : y + thumbnail_height, x : x + thumbnail_width] = image
        relative_sec = float(record.get("relative_sec", 0.0))
        label = f"#{frame_index:06d}  t={relative_sec:.2f}s"
        cv2.putText(
            sheet,
            label,
            (x + 8, y + thumbnail_height + 22),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (25, 25, 25),
            1,
            cv2.LINE_AA,
        )
    contact_sheet_path = artifacts_dir / "contact_sheet.jpg"
    if not cv2.imwrite(
        str(contact_sheet_path), sheet, [int(cv2.IMWRITE_JPEG_QUALITY), 92]
    ):
        raise RuntimeError(f"failed to write contact sheet: {contact_sheet_path}")

    output_fps = preview_fps or _estimated_fps(records)
    preview_path: Path | None = None
    preview_codec: str | None = None
    if create_video:
        first = _load_frame(session_dir, records[0])
        height, width = first.shape[:2]
        preview_path = artifacts_dir / "preview.mp4"
        writer = None
        for codec in ("avc1", "mp4v"):
            candidate = cv2.VideoWriter(
                str(preview_path),
                cv2.VideoWriter_fourcc(*codec),
                output_fps,
                (width, height),
            )
            if candidate.isOpened():
                writer = candidate
                preview_codec = codec
                break
            candidate.release()
        if writer is None:
            raise RuntimeError("OpenCV could not initialize the MP4 preview encoder")
        try:
            for record in records:
                image = _load_frame(session_dir, record)
                if image.shape[1] != width or image.shape[0] != height:
                    image = _letterbox(image, width, height)
                cv2.putText(
                    image,
                    f"frame {int(record['index']):06d}  "
                    f"t={float(record.get('relative_sec', 0.0)):.2f}s",
                    (16, 28),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 0, 0),
                    3,
                    cv2.LINE_AA,
                )
                cv2.putText(
                    image,
                    f"frame {int(record['index']):06d}  "
                    f"t={float(record.get('relative_sec', 0.0)):.2f}s",
                    (16, 28),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (255, 255, 255),
                    1,
                    cv2.LINE_AA,
                )
                writer.write(image)
        finally:
            writer.release()
        if not preview_path.is_file() or preview_path.stat().st_size == 0:
            raise RuntimeError(f"failed to write preview video: {preview_path}")

    duck = metadata.get("duck", {})
    dimensions = sorted({(item["width"], item["height"]) for item in records})
    report_path = artifacts_dir / "report.html"
    preview_link = (
        '<video controls preload="metadata"><source src="preview.mp4" '
        'type="video/mp4">Open <a href="preview.mp4">preview.mp4</a>.</video>'
        if preview_path is not None
        else ""
    )
    gallery = "".join(
        f'<figure><a href="../frames/{html.escape(str(records[index]["filename"]))}">'
        f'<img loading="lazy" src="../frames/{html.escape(str(records[index]["filename"]))}" '
        f'alt="frame {index}"></a><figcaption>#{index:06d} · '
        f'{float(records[index].get("relative_sec", 0.0)):.2f}s</figcaption></figure>'
        for index in sampled_indices
    )
    report_html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Duck dataset session {html.escape(str(metadata.get('session_id')))}</title>
  <style>
    body {{ font-family: sans-serif; max-width: 1400px; margin: 2rem auto; padding: 0 1rem; }}
    table {{ border-collapse: collapse; }}
    td, th {{ border: 1px solid #bbb; padding: 0.45rem 0.7rem; text-align: left; }}
    img, video {{ max-width: 100%; height: auto; }}
    video {{ width: 100%; margin-top: 1.5rem; background: #111; }}
    .gallery {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 1rem; }}
    figure {{ margin: 0; }} figure img {{ width: 100%; }} figcaption {{ color: #666; }}
  </style>
</head>
<body>
  <h1>Duck dataset session</h1>
  <table>
    <tr><th>Session</th><td>{html.escape(str(metadata.get('session_id')))}</td></tr>
    <tr><th>Scene</th><td>{html.escape(str(metadata.get('scene')))}</td></tr>
    <tr><th>Duck present</th><td>{html.escape(str(duck.get('present')))}</td></tr>
    <tr><th>Duck count</th><td>{html.escape(str(duck.get('count')))}</td></tr>
    <tr><th>Frames</th><td>{len(records)}</td></tr>
    <tr><th>Dimensions</th><td>{html.escape(str(dimensions))}</td></tr>
    <tr><th>Preview FPS</th><td>{output_fps:.3f}</td></tr>
  </table>
  {preview_link}
  <h2>Contact sheet</h2>
  <img src="contact_sheet.jpg" alt="Contact sheet">
  <h2>Sampled original frames</h2>
  <div class="gallery">{gallery}</div>
</body>
</html>
"""
    report_path.write_text(report_html, encoding="utf-8")

    summary = {
        "schema_version": 1,
        "created_at": now_iso(),
        "session_id": metadata.get("session_id"),
        "frame_count": len(records),
        "sampled_frames": sampled_indices,
        "contact_sheet": str(contact_sheet_path),
        "preview_video": str(preview_path) if preview_path else None,
        "preview_fps": output_fps,
        "preview_codec": preview_codec,
        "html_report": str(report_path),
    }
    (artifacts_dir / "visualization_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary
