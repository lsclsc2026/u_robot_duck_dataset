#!/usr/bin/env python3
"""Build a traceable Grounding DINO/SAM2 validation subset.

The source session directories are treated as immutable. Grounding DINO gets
temporally distributed still images; SAM2 gets complete, consecutive frame
windows with filenames renumbered from zero.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np
import yaml


DEFAULT_DATA_ROOT = Path(os.environ.get("U_ROBOT_DUCK_DATA_ROOT", str(Path.home() / "data" / "duck_dataset")))
BENCHMARK_NAME = "grounded_sam2_v1"
EXPECTED_DIMENSIONS = (960, 540)
SIMILARITY_DISTANCE = 10

GROUNDING_SPLITS: dict[str, tuple[tuple[str, int], ...]] = {
    "calibration": (
        ("20260903_061720_room_a_duck_repositioned", 45),
        ("20260903_073208_room_a_duck_repositioned", 55),
    ),
    "holdout": (
        ("20260903_053540_room_a", 15),
        ("20260903_071223_room_a_duck_repositioned", 45),
    ),
}


@dataclass(frozen=True)
class ClipSpec:
    name: str
    session_id: str
    start_sec: float
    end_sec: float


CLIP_SPECS = (
    ClipSpec(
        "061720_multi_far",
        "20260903_061720_room_a_duck_repositioned",
        90.0,
        120.0,
    ),
    ClipSpec(
        "071223_open_floor",
        "20260903_071223_room_a_duck_repositioned",
        0.0,
        30.0,
    ),
    ClipSpec(
        "073208_chair_multi",
        "20260903_073208_room_a_duck_repositioned",
        110.0,
        150.0,
    ),
    ClipSpec(
        "073208_edge_far",
        "20260903_073208_room_a_duck_repositioned",
        250.0,
        280.0,
    ),
)


@dataclass(frozen=True)
class FrameMetric:
    session_id: str
    session_dir: Path
    record: dict[str, Any]
    source_path: Path
    blur_score: float
    brightness: float
    perceptual_hash: str


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _load_manifest(session_dir: Path) -> list[dict[str, Any]]:
    manifest = session_dir / "frames" / "frames.jsonl"
    if not manifest.is_file():
        raise FileNotFoundError(f"missing frame manifest: {manifest}")
    records: list[dict[str, Any]] = []
    with manifest.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            for key in ("index", "filename", "relative_sec", "sha256"):
                if key not in record:
                    raise ValueError(f"{manifest}:{line_number} missing {key}")
            records.append(record)
    if not records:
        raise ValueError(f"empty frame manifest: {manifest}")
    indices = [int(record["index"]) for record in records]
    if indices != list(range(len(records))):
        raise ValueError(f"non-contiguous frame indices: {manifest}")
    timestamps = [float(record["relative_sec"]) for record in records]
    if any(right <= left for left, right in zip(timestamps, timestamps[1:])):
        raise ValueError(f"frame timestamps are not strictly increasing: {manifest}")
    return records


def _one_hz_candidates(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Choose the record nearest the middle of each elapsed one-second bin."""
    by_second: dict[int, list[dict[str, Any]]] = {}
    for record in records:
        second = int(math.floor(float(record["relative_sec"])))
        by_second.setdefault(second, []).append(record)
    candidates = []
    for second in sorted(by_second):
        midpoint = second + 0.5
        candidates.append(
            min(
                by_second[second],
                key=lambda item: abs(float(item["relative_sec"]) - midpoint),
            )
        )
    return candidates


def _dhash(gray: np.ndarray) -> str:
    resized = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    bits = resized[:, 1:] > resized[:, :-1]
    value = 0
    for bit in bits.flat:
        value = (value << 1) | int(bit)
    return f"{value:016x}"


def _hash_distance(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


def _measure_frame(
    session_id: str, session_dir: Path, record: dict[str, Any]
) -> FrameMetric:
    source_path = session_dir / "frames" / str(record["filename"])
    image = cv2.imread(str(source_path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"cannot decode source image: {source_path}")
    height, width = image.shape[:2]
    if (width, height) != EXPECTED_DIMENSIONS:
        raise ValueError(
            f"unexpected dimensions for {source_path}: {width}x{height}"
        )
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return FrameMetric(
        session_id=session_id,
        session_dir=session_dir,
        record=record,
        source_path=source_path,
        blur_score=float(cv2.Laplacian(gray, cv2.CV_64F).var()),
        brightness=float(gray.mean()),
        perceptual_hash=_dhash(gray),
    )


def _select_metrics(candidates: list[FrameMetric], target: int) -> list[FrameMetric]:
    if target <= 0:
        raise ValueError("selection target must be positive")
    if len(candidates) < target:
        raise ValueError(f"need {target} candidates, found only {len(candidates)}")

    selected: list[FrameMetric] = []
    count = len(candidates)
    for slot in range(target):
        start = math.floor(slot * count / target)
        stop = max(start + 1, math.floor((slot + 1) * count / target))
        bucket = candidates[start:stop]
        # Roughly ten percent deliberately prefer a difficult/blurry frame.
        prefer_difficult = slot % 10 == 9
        ranked = sorted(
            bucket,
            key=lambda item: item.blur_score,
            reverse=not prefer_difficult,
        )
        non_similar = [
            item
            for item in ranked
            if all(
                _hash_distance(item.perceptual_hash, prior.perceptual_hash)
                >= SIMILARITY_DISTANCE
                for prior in selected
            )
        ]
        selected.append((non_similar or ranked)[0])

    selected.sort(key=lambda item: float(item.record["relative_sec"]))
    if len({int(item.record["index"]) for item in selected}) != target:
        raise RuntimeError("selection unexpectedly contains duplicate frame indices")
    return selected


def _records_for_clip(
    records: list[dict[str, Any]], start_sec: float, end_sec: float
) -> list[dict[str, Any]]:
    if start_sec < 0 or end_sec <= start_sec:
        raise ValueError("invalid clip time range")
    selected = [
        record
        for record in records
        if start_sec <= float(record["relative_sec"]) < end_sec
    ]
    if not selected:
        raise ValueError(f"no frames in clip range [{start_sec}, {end_sec})")
    timestamps = [float(record["relative_sec"]) for record in selected]
    if any(right <= left for left, right in zip(timestamps, timestamps[1:])):
        raise ValueError("clip timestamps are not strictly increasing")
    return selected


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _benchmark_output(data_root: Path) -> Path:
    root = data_root.expanduser().resolve()
    return root / "benchmarks" / BENCHMARK_NAME


def _assert_safe_output(data_root: Path, output: Path) -> None:
    expected = _benchmark_output(data_root)
    if output.resolve() != expected:
        raise ValueError(f"refusing unexpected benchmark output path: {output}")
    sessions = data_root.expanduser().resolve() / "sessions"
    if output.resolve() == sessions or sessions in output.resolve().parents:
        raise ValueError("benchmark output must never be inside sessions")


def _copy_verified(source: Path, destination: Path, expected_hash: str) -> None:
    actual_source_hash = _sha256(source)
    if actual_source_hash != expected_hash:
        raise ValueError(f"source SHA256 mismatch: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if _sha256(destination) != expected_hash:
        raise RuntimeError(f"copied SHA256 mismatch: {destination}")
    image = cv2.imread(str(destination), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"cannot decode copied image: {destination}")
    height, width = image.shape[:2]
    if (width, height) != EXPECTED_DIMENSIONS:
        raise ValueError(f"unexpected copied dimensions: {destination}")


def _contact_sheet(entries: list[dict[str, Any]], base: Path, output: Path) -> None:
    columns = 5
    width, height, label_height = 320, 180, 34
    rows = math.ceil(len(entries) / columns)
    sheet = np.full((rows * (height + label_height), columns * width, 3), 238, np.uint8)
    for position, entry in enumerate(entries):
        image = cv2.imread(str(base / entry["relative_path"]), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"cannot build contact sheet for {entry['relative_path']}")
        image = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
        row, column = divmod(position, columns)
        x, y = column * width, row * (height + label_height)
        sheet[y : y + height, x : x + width] = image
        label = f"{entry['source_session'][9:15]} #{entry['source_frame_index']:06d} {entry['relative_sec']:.1f}s"
        cv2.putText(
            sheet,
            label,
            (x + 5, y + height + 23),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (25, 25, 25),
            1,
            cv2.LINE_AA,
        )
    if not cv2.imwrite(str(output), sheet, [int(cv2.IMWRITE_JPEG_QUALITY), 90]):
        raise RuntimeError(f"failed to write contact sheet: {output}")


def _write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def _prepare_plan(data_root: Path) -> dict[str, Any]:
    sessions_root = data_root / "sessions"
    split_sessions = {
        split: {session_id for session_id, _ in allocations}
        for split, allocations in GROUNDING_SPLITS.items()
    }
    if split_sessions["calibration"] & split_sessions["holdout"]:
        raise ValueError("calibration and holdout sessions overlap")

    manifests: dict[str, list[dict[str, Any]]] = {}
    grounding: dict[str, list[FrameMetric]] = {}
    for split, allocations in GROUNDING_SPLITS.items():
        grounding[split] = []
        for session_id, target in allocations:
            session_dir = sessions_root / session_id
            records = manifests.setdefault(session_id, _load_manifest(session_dir))
            candidates = [
                _measure_frame(session_id, session_dir, record)
                for record in _one_hz_candidates(records)
            ]
            grounding[split].extend(_select_metrics(candidates, target))

    clips: dict[str, tuple[ClipSpec, Path, list[dict[str, Any]]]] = {}
    for spec in CLIP_SPECS:
        session_dir = sessions_root / spec.session_id
        records = manifests.setdefault(spec.session_id, _load_manifest(session_dir))
        clips[spec.name] = (
            spec,
            session_dir,
            _records_for_clip(records, spec.start_sec, spec.end_sec),
        )
    return {"grounding": grounding, "clips": clips}


def _build(
    data_root: Path, output: Path, plan: dict[str, Any]
) -> tuple[dict[str, Any], Path]:
    benchmark_parent = output.parent
    benchmark_parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{BENCHMARK_NAME}.tmp-", dir=benchmark_parent))
    try:
        grounding_root = staging / "grounding_dino"
        manifest_entries: list[dict[str, Any]] = []
        split_entries: dict[str, list[dict[str, Any]]] = {}
        for split, metrics in plan["grounding"].items():
            split_entries[split] = []
            image_dir = grounding_root / split / "images"
            image_dir.mkdir(parents=True)
            for metric in metrics:
                frame_index = int(metric.record["index"])
                filename = f"{metric.session_id}__{frame_index:06d}.jpg"
                destination = image_dir / filename
                _copy_verified(
                    metric.source_path, destination, str(metric.record["sha256"])
                )
                entry = {
                    "benchmark_split": split,
                    "benchmark_filename": filename,
                    "relative_path": destination.relative_to(staging).as_posix(),
                    "source_session": metric.session_id,
                    "source_frame_index": frame_index,
                    "source_filename": str(metric.record["filename"]),
                    "relative_sec": float(metric.record["relative_sec"]),
                    "width": int(metric.record.get("width", EXPECTED_DIMENSIONS[0])),
                    "height": int(metric.record.get("height", EXPECTED_DIMENSIONS[1])),
                    "sha256": str(metric.record["sha256"]),
                    "blur_score": round(metric.blur_score, 6),
                    "brightness": round(metric.brightness, 6),
                    "perceptual_hash": metric.perceptual_hash,
                    "annotation_status": "unreviewed",
                }
                manifest_entries.append(entry)
                split_entries[split].append(entry)

        _write_jsonl(grounding_root / "manifest.jsonl", manifest_entries)
        for split, entries in split_entries.items():
            _contact_sheet(
                entries,
                staging,
                grounding_root / f"contact_sheet_{split}.jpg",
            )

        clip_summaries: dict[str, Any] = {}
        for name, (spec, session_dir, records) in plan["clips"].items():
            clip_root = staging / "sam2_clips" / name
            frame_dir = clip_root / "frames"
            frame_dir.mkdir(parents=True)
            mappings: list[dict[str, Any]] = []
            for new_index, record in enumerate(records):
                new_filename = f"{new_index:06d}.jpg"
                source = session_dir / "frames" / str(record["filename"])
                destination = frame_dir / new_filename
                _copy_verified(source, destination, str(record["sha256"]))
                mappings.append(
                    {
                        "clip_frame_index": new_index,
                        "clip_filename": new_filename,
                        "source_session": spec.session_id,
                        "source_frame_index": int(record["index"]),
                        "source_filename": str(record["filename"]),
                        "relative_sec": float(record["relative_sec"]),
                        "sha256": str(record["sha256"]),
                    }
                )
            _write_jsonl(clip_root / "mapping.jsonl", mappings)
            clip_metadata = {
                "schema_version": 1,
                "created_at": _now_iso(),
                "clip_name": name,
                "source_session": spec.session_id,
                "requested_start_sec": spec.start_sec,
                "requested_end_sec": spec.end_sec,
                "actual_start_sec": mappings[0]["relative_sec"],
                "actual_end_sec": mappings[-1]["relative_sec"],
                "frame_count": len(mappings),
                "dimensions": list(EXPECTED_DIMENSIONS),
            }
            (clip_root / "clip.yaml").write_text(
                yaml.safe_dump(clip_metadata, sort_keys=False), encoding="utf-8"
            )
            clip_summaries[name] = clip_metadata

        split_counts = {split: len(entries) for split, entries in split_entries.items()}
        if split_counts != {"calibration": 100, "holdout": 60}:
            raise RuntimeError(f"unexpected grounding split counts: {split_counts}")
        summary = {
            "schema_version": 1,
            "created_at": _now_iso(),
            "benchmark_name": BENCHMARK_NAME,
            "source_data_root": str(data_root),
            "grounding_dino": {
                "total_images": len(manifest_entries),
                "split_counts": split_counts,
                "session_counts": {
                    split: {
                        session_id: sum(
                            entry["source_session"] == session_id
                            for entry in split_entries[split]
                        )
                        for session_id, _ in GROUNDING_SPLITS[split]
                    }
                    for split in GROUNDING_SPLITS
                },
                "labels_created": False,
            },
            "sam2_clips": clip_summaries,
            "checks": {
                "grounding_total_is_160": len(manifest_entries) == 160,
                "session_splits_disjoint": True,
                "sha256_verified": True,
                "images_decodable": True,
                "dimensions_are_960x540": True,
                "clip_filenames_contiguous": True,
                "clip_timestamps_increasing": True,
            },
            "true_negative_session_available": False,
            "warning": (
                "No duck.present=false session was included. Do not infer true "
                "negative labels from model non-detections."
            ),
        }
        (staging / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        report = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{BENCHMARK_NAME}</title>
<style>body{{font-family:sans-serif;max-width:1400px;margin:2rem auto;padding:0 1rem}}
img{{max-width:100%;height:auto}} code{{background:#eee;padding:.15rem .3rem}}</style></head>
<body><h1>Grounded SAM2 validation set</h1>
<p><strong>160 unreviewed images.</strong> Missing label files do not mean negative samples.</p>
<h2>Calibration ({split_counts['calibration']})</h2>
<img src="contact_sheet_calibration.jpg" alt="Calibration contact sheet">
<h2>Holdout ({split_counts['holdout']})</h2>
<img src="contact_sheet_holdout.jpg" alt="Holdout contact sheet">
<p>Traceability: <a href="manifest.jsonl">manifest.jsonl</a>. Overall summary:
<a href="../summary.json">summary.json</a>.</p></body></html>"""
        (grounding_root / "report.html").write_text(report, encoding="utf-8")
        return summary, staging
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _print_plan(plan: dict[str, Any], output: Path, dry_run: bool) -> None:
    print(f"Mode: {'dry-run' if dry_run else 'build'}")
    print(f"Output: {output}")
    print("Grounding DINO selections:")
    for split, metrics in plan["grounding"].items():
        by_session: dict[str, int] = {}
        for metric in metrics:
            by_session[metric.session_id] = by_session.get(metric.session_id, 0) + 1
        print(f"  {split}: {len(metrics)} images {by_session}")
    print("SAM2 clips:")
    for name, (spec, _session_dir, records) in plan["clips"].items():
        print(
            f"  {name}: {len(records)} frames, {spec.start_sec:.1f}s-"
            f"{spec.end_sec:.1f}s, session={spec.session_id}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the first Grounding DINO + SAM2 validation subset"
    )
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    data_root = arguments.data_root.expanduser().resolve()
    output = _benchmark_output(data_root)
    _assert_safe_output(data_root, output)
    if output.exists() and not arguments.overwrite and not arguments.dry_run:
        raise FileExistsError(f"output already exists; use --overwrite: {output}")

    plan = _prepare_plan(data_root)
    _print_plan(plan, output, arguments.dry_run)
    if arguments.dry_run:
        print("Dry-run complete; no files were written.")
        return 0

    result = _build(data_root, output, plan)
    summary, staging = result
    if output.exists():
        _assert_safe_output(data_root, output)
        shutil.rmtree(output)
    os.replace(staging, output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Validation set created: {output}")
    print(f"Review: {output / 'grounding_dino' / 'report.html'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileExistsError, FileNotFoundError, RuntimeError, TypeError, ValueError) as error:
        raise SystemExit(f"error: {error}") from error
