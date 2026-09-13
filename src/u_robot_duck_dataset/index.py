"""Build a static browser index for all capture sessions."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

from .session import DEFAULT_DATA_ROOT, now_iso


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        payload = yaml.safe_load(stream)
    return payload if isinstance(payload, dict) else {}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _value(value: Any) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    if value is None:
        return "unknown"
    return str(value)


def build_dataset_index(root: Path = DEFAULT_DATA_ROOT) -> dict[str, Any]:
    root = root.expanduser().resolve()
    sessions_dir = root / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    cards: list[str] = []
    session_summaries: list[dict[str, Any]] = []

    for session_dir in sorted(sessions_dir.iterdir(), reverse=True):
        metadata_path = session_dir / "session.yaml"
        if not session_dir.is_dir() or not metadata_path.is_file():
            continue
        try:
            metadata = _read_yaml(metadata_path)
        except (OSError, yaml.YAMLError) as error:
            metadata = {
                "session_id": session_dir.name,
                "status": "metadata_error",
                "scene": f"Invalid metadata: {error}",
            }
        validation = _read_json(session_dir / "artifacts" / "validation_report.json")
        session_id = str(metadata.get("session_id", session_dir.name))
        escaped_id = html.escape(session_id)
        encoded_id = quote(session_dir.name)
        status = str(metadata.get("status", "unknown"))
        validation_status = str(validation.get("status", "not_run"))
        frame_count = validation.get(
            "frame_count", metadata.get("extraction", {}).get("frame_count", 0)
        )
        estimated_fps = validation.get("estimated_fps")
        fps_text = f"{float(estimated_fps):.2f}" if estimated_fps else "—"
        dimensions = validation.get("dimensions") or []
        dimension_text = (
            ", ".join(
                f"{item.get('width')}×{item.get('height')}" for item in dimensions
            )
            or "—"
        )
        duck = metadata.get("duck", {})
        conditions = metadata.get("conditions", {})
        artifacts = session_dir / "artifacts"
        contact_sheet = artifacts / "contact_sheet.jpg"
        report = artifacts / "report.html"
        preview = artifacts / "preview.mp4"
        visual = (
            f'<a class="thumb" href="sessions/{encoded_id}/artifacts/report.html">'
            f'<img loading="lazy" src="sessions/{encoded_id}/artifacts/contact_sheet.jpg" '
            f'alt="Contact sheet for {escaped_id}"></a>'
            if contact_sheet.is_file() and report.is_file()
            else '<div class="missing">No visualization yet</div>'
        )
        links: list[str] = []
        if report.is_file():
            links.append(
                f'<a href="sessions/{encoded_id}/artifacts/report.html">Report</a>'
            )
        if contact_sheet.is_file():
            links.append(
                f'<a href="sessions/{encoded_id}/artifacts/contact_sheet.jpg">Contact sheet</a>'
            )
        if preview.is_file():
            links.append(
                f'<a href="sessions/{encoded_id}/artifacts/preview.mp4">Video</a>'
            )
        links.append(f'<a href="sessions/{encoded_id}/session.yaml">Metadata</a>')
        cards.append(
            f"""
<article class="card">
  <div class="card-head">
    <div><h2>{escaped_id}</h2><p>{html.escape(str(metadata.get('scene', 'unknown')))}</p></div>
    <span class="status {html.escape(status)}">{html.escape(status)}</span>
  </div>
  {visual}
  <dl>
    <dt>Validation</dt><dd>{html.escape(validation_status)}</dd>
    <dt>Frames</dt><dd>{html.escape(str(frame_count))}</dd>
    <dt>FPS</dt><dd>{fps_text}</dd>
    <dt>Dimensions</dt><dd>{html.escape(dimension_text)}</dd>
    <dt>Duck present</dt><dd>{html.escape(_value(duck.get('present')))}</dd>
    <dt>Duck count</dt><dd>{html.escape(_value(duck.get('count')))}</dd>
    <dt>Lighting</dt><dd>{html.escape(_value(conditions.get('lighting')))}</dd>
  </dl>
  <nav>{' · '.join(links)}</nav>
</article>
"""
        )
        session_summaries.append(
            {
                "session_id": session_id,
                "status": status,
                "validation_status": validation_status,
                "frame_count": frame_count,
                "has_visualization": contact_sheet.is_file(),
            }
        )

    generated_at = now_iso()
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Unitree duck dataset</title>
  <style>
    :root {{ color-scheme: light dark; font-family: system-ui, sans-serif; }}
    body {{ max-width: 1500px; margin: auto; padding: 2rem; background: #111827; color: #e5e7eb; }}
    header {{ display: flex; justify-content: space-between; align-items: end; gap: 2rem; margin-bottom: 1.5rem; }}
    h1, h2, p {{ margin: 0; }}
    header p, .card-head p {{ color: #9ca3af; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(350px, 1fr)); gap: 1.2rem; }}
    .card {{ border: 1px solid #374151; border-radius: 12px; overflow: hidden; background: #1f2937; box-shadow: 0 7px 18px #0005; }}
    .card-head {{ display: flex; justify-content: space-between; gap: 1rem; padding: 1rem; }}
    .card h2 {{ font-size: 1rem; overflow-wrap: anywhere; }}
    .thumb {{ display: block; background: #030712; }}
    .thumb img {{ width: 100%; aspect-ratio: 16 / 9; object-fit: cover; display: block; }}
    .missing {{ aspect-ratio: 16 / 9; display: grid; place-items: center; background: #030712; color: #6b7280; }}
    .status {{ border-radius: 999px; padding: .25rem .6rem; height: fit-content; background: #4b5563; font-size: .8rem; }}
    .status.validated {{ background: #065f46; }}
    .status.record_failed {{ background: #991b1b; }}
    .status.recorded {{ background: #92400e; }}
    dl {{ display: grid; grid-template-columns: 1fr 1fr; padding: 0 1rem; font-size: .9rem; }}
    dt {{ color: #9ca3af; }} dd {{ margin: 0; text-align: right; }}
    nav {{ padding: 0 1rem 1rem; }} a {{ color: #60a5fa; }}
    @media (max-width: 600px) {{ body {{ padding: 1rem; }} header {{ display: block; }} }}
  </style>
</head>
<body>
  <header>
    <div><h1>Unitree yellow-duck dataset</h1><p>{len(session_summaries)} capture sessions</p></div>
    <p><a href="/live">Live camera</a> · Generated {html.escape(generated_at)}</p>
  </header>
  <main class="grid">{''.join(cards) if cards else '<p>No sessions found.</p>'}</main>
</body>
</html>
"""
    index_path = root / "index.html"
    index_path.write_text(page, encoding="utf-8")
    summary = {
        "schema_version": 1,
        "generated_at": generated_at,
        "root": str(root),
        "index": str(index_path),
        "session_count": len(session_summaries),
        "sessions": session_summaries,
    }
    (root / "index_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary
