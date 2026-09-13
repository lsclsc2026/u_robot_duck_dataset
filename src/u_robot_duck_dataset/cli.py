"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .extract import extract_frames
from .index import build_dataset_index
from .session import (
    DEFAULT_DATA_ROOT,
    DEFAULT_TOPIC,
    create_session,
    mark_record_failed,
    mark_recording,
    mark_recorded,
    parse_presence,
)
from .validate import validate_session
from .visualize import create_visualization


def _json_print(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="duck-dataset",
        description="Capture preparation tools for the Unitree yellow-duck dataset",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="create a new capture session")
    init.add_argument("--root", type=Path, default=DEFAULT_DATA_ROOT)
    init.add_argument("--session-id")
    init.add_argument("--scene", required=True)
    init.add_argument(
        "--duck-present", default="unknown", choices=("true", "false", "unknown")
    )
    init.add_argument("--duck-count", type=int)
    init.add_argument("--lighting", default="unknown")
    init.add_argument("--distance-range", default="unknown")
    init.add_argument("--occlusion", default="unknown")
    init.add_argument("--notes", default="")
    init.add_argument("--topic", default=DEFAULT_TOPIC)

    recorded = subparsers.add_parser(
        "mark-recorded", help="record the bag path in session metadata"
    )
    recorded.add_argument("--session", type=Path, required=True)
    recorded.add_argument("--bag", type=Path, required=True)

    recording = subparsers.add_parser(
        "mark-recording", help="mark a capture session as actively recording"
    )
    recording.add_argument("--session", type=Path, required=True)
    recording.add_argument("--bag", type=Path, required=True)

    failed = subparsers.add_parser(
        "mark-record-failed", help="record a capture failure in session metadata"
    )
    failed.add_argument("--session", type=Path, required=True)
    failed.add_argument("--reason", required=True)

    extract = subparsers.add_parser(
        "extract", help="extract compressed frames from a ROS 2 bag"
    )
    extract.add_argument("--session", type=Path, required=True)
    extract.add_argument("--bag", type=Path)
    extract.add_argument("--topic")
    extract.add_argument("--sample-fps", type=float, default=0.0)
    extract.add_argument("--start-sec", type=float, default=0.0)
    extract.add_argument("--end-sec", type=float)
    extract.add_argument("--max-frames", type=int)
    extract.add_argument("--overwrite", action="store_true")

    validate = subparsers.add_parser(
        "validate", help="validate extracted frame files and timestamps"
    )
    validate.add_argument("--session", type=Path, required=True)
    validate.add_argument("--skip-hashes", action="store_true")

    visualize = subparsers.add_parser(
        "visualize", help="create a contact sheet and preview video"
    )
    visualize.add_argument("--session", type=Path, required=True)
    visualize.add_argument("--samples", type=int, default=24)
    visualize.add_argument("--columns", type=int, default=4)
    visualize.add_argument("--thumbnail-width", type=int, default=320)
    visualize.add_argument("--thumbnail-height", type=int, default=180)
    visualize.add_argument("--preview-fps", type=float, default=0.0)
    visualize.add_argument("--no-video", action="store_true")

    index = subparsers.add_parser(
        "index", help="build a static browser index for all sessions"
    )
    index.add_argument("--root", type=Path, default=DEFAULT_DATA_ROOT)

    serve = subparsers.add_parser(
        "serve", help="serve dataset reports and a live camera monitor"
    )
    serve.add_argument("--root", type=Path, default=DEFAULT_DATA_ROOT)
    serve.add_argument("--bind", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8090)
    serve.add_argument("--topic", default=DEFAULT_TOPIC)
    return parser


def run(arguments: argparse.Namespace) -> int:
    if arguments.command == "init":
        session_dir = create_session(
            root=arguments.root,
            scene=arguments.scene,
            duck_present=parse_presence(arguments.duck_present),
            duck_count=arguments.duck_count,
            lighting=arguments.lighting,
            distance_range=arguments.distance_range,
            occlusion=arguments.occlusion,
            notes=arguments.notes,
            topic=arguments.topic,
            session_id=arguments.session_id,
        )
        print(session_dir)
        return 0
    if arguments.command == "mark-recorded":
        mark_recorded(arguments.session, arguments.bag)
        print(arguments.session.expanduser().resolve())
        return 0
    if arguments.command == "mark-recording":
        mark_recording(arguments.session, arguments.bag)
        print(arguments.session.expanduser().resolve())
        return 0
    if arguments.command == "mark-record-failed":
        mark_record_failed(arguments.session, arguments.reason)
        print(arguments.session.expanduser().resolve())
        return 0
    if arguments.command == "extract":
        _json_print(
            extract_frames(
                session_dir=arguments.session,
                bag_dir=arguments.bag,
                topic=arguments.topic,
                sample_fps=arguments.sample_fps,
                start_sec=arguments.start_sec,
                end_sec=arguments.end_sec,
                max_frames=arguments.max_frames,
                overwrite=arguments.overwrite,
            )
        )
        return 0
    if arguments.command == "validate":
        report = validate_session(
            session_dir=arguments.session, verify_hashes=not arguments.skip_hashes
        )
        _json_print(report)
        return 0 if report["status"] == "ok" else 2
    if arguments.command == "visualize":
        _json_print(
            create_visualization(
                session_dir=arguments.session,
                sample_count=arguments.samples,
                columns=arguments.columns,
                thumbnail_width=arguments.thumbnail_width,
                thumbnail_height=arguments.thumbnail_height,
                preview_fps=arguments.preview_fps,
                create_video=not arguments.no_video,
            )
        )
        return 0
    if arguments.command == "index":
        _json_print(build_dataset_index(arguments.root))
        return 0
    if arguments.command == "serve":
        if not 1 <= arguments.port <= 65535:
            raise ValueError("server port must be in [1, 65535]")
        from .web import serve_dataset

        serve_dataset(
            root=arguments.root,
            bind_address=arguments.bind,
            port=arguments.port,
            topic=arguments.topic,
        )
        return 0
    raise AssertionError(f"unhandled command: {arguments.command}")


def main() -> None:
    parser = build_parser()
    try:
        status = run(parser.parse_args())
    except (FileNotFoundError, FileExistsError, RuntimeError, TypeError, ValueError) as error:
        parser.exit(1, f"error: {error}\n")
    sys.exit(status)
