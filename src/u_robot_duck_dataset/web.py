"""Static dataset browser with a live ROS CompressedImage monitor."""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

from .index import build_dataset_index


class LiveCameraState:
    def __init__(self, topic: str) -> None:
        self.topic = topic
        self.condition = threading.Condition()
        self.jpeg: bytes | None = None
        self.sequence = 0
        self.received_frames = 0
        self.last_received_monotonic: float | None = None
        self.receive_times: deque[float] = deque(maxlen=60)
        self.ros_available = False
        self.error: str | None = None

    def update(self, jpeg: bytes) -> None:
        now = time.monotonic()
        with self.condition:
            self.jpeg = jpeg
            self.sequence += 1
            self.received_frames += 1
            self.last_received_monotonic = now
            self.receive_times.append(now)
            self.condition.notify_all()

    def snapshot(self) -> dict[str, Any]:
        with self.condition:
            age = (
                None
                if self.last_received_monotonic is None
                else time.monotonic() - self.last_received_monotonic
            )
            fps = None
            if len(self.receive_times) > 1:
                duration = self.receive_times[-1] - self.receive_times[0]
                if duration > 0:
                    fps = (len(self.receive_times) - 1) / duration
            return {
                "topic": self.topic,
                "ros_available": self.ros_available,
                "stream_available": self.jpeg is not None and age is not None and age < 3.0,
                "received_frames": self.received_frames,
                "fps": fps,
                "last_frame_age_sec": age,
                "error": self.error,
            }


def _latest_session(root: Path) -> dict[str, Any] | None:
    sessions_dir = root / "sessions"
    if not sessions_dir.is_dir():
        return None
    candidates = sorted(
        (
            path
            for path in sessions_dir.iterdir()
            if (path / "session.yaml").is_file()
        ),
        reverse=True,
    )
    if not candidates:
        return None
    session_dir = candidates[0]
    try:
        metadata = yaml.safe_load(
            (session_dir / "session.yaml").read_text(encoding="utf-8")
        )
    except (OSError, yaml.YAMLError) as error:
        return {
            "session_id": session_dir.name,
            "status": "metadata_error",
            "error": str(error),
        }
    if not isinstance(metadata, dict):
        metadata = {}
    bag_path = metadata.get("paths", {}).get("bag")
    bag_dir = session_dir / bag_path if bag_path else session_dir / "raw" / "camera_bag"
    bag_bytes = sum(
        file.stat().st_size for file in bag_dir.glob("*.db3") if file.is_file()
    )
    return {
        "session_id": metadata.get("session_id", session_dir.name),
        "status": metadata.get("status", "unknown"),
        "scene": metadata.get("scene", "unknown"),
        "duck_present": metadata.get("duck", {}).get("present"),
        "bag_bytes": bag_bytes,
        "frame_count": metadata.get("extraction", {}).get("frame_count"),
    }


def _live_page() -> bytes:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Unitree live camera</title>
  <style>
    :root { color-scheme: dark; font-family: system-ui, sans-serif; }
    body { max-width: 1200px; margin: auto; padding: 1.5rem; background: #0b1120; color: #e5e7eb; }
    header { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
    a { color: #60a5fa; }
    .panel { background: #111827; border: 1px solid #374151; border-radius: 12px; padding: 1rem; margin-top: 1rem; }
    #stream { display: block; width: 100%; aspect-ratio: 16 / 9; object-fit: contain; background: #000; border-radius: 8px; }
    .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: .7rem; margin-top: 1rem; }
    .stat { background: #1f2937; padding: .7rem; border-radius: 8px; }
    .label { color: #9ca3af; font-size: .8rem; }
    .value { font-size: 1.05rem; overflow-wrap: anywhere; }
    .dot { display: inline-block; width: .75rem; height: .75rem; border-radius: 50%; background: #991b1b; margin-right: .4rem; }
    .dot.ok { background: #10b981; }
  </style>
</head>
<body>
  <header><div><h1>Live camera monitor</h1><p><span id="dot" class="dot"></span><span id="health">Waiting for camera...</span></p></div><a href="/">Dataset sessions</a></header>
  <section class="panel"><img id="stream" src="/stream.mjpg" alt="Live Unitree front camera"></section>
  <section class="stats">
    <div class="stat"><div class="label">Camera FPS</div><div id="fps" class="value">—</div></div>
    <div class="stat"><div class="label">Last frame age</div><div id="age" class="value">—</div></div>
    <div class="stat"><div class="label">Frames observed</div><div id="observed" class="value">0</div></div>
    <div class="stat"><div class="label">Latest session</div><div id="session" class="value">—</div></div>
    <div class="stat"><div class="label">Session status</div><div id="status" class="value">—</div></div>
    <div class="stat"><div class="label">Bag size</div><div id="size" class="value">—</div></div>
  </section>
  <script>
    const formatBytes = n => n == null ? '—' : (n / 1048576).toFixed(1) + ' MiB';
    async function update() {
      try {
        const response = await fetch('/api/live', {cache: 'no-store'});
        const data = await response.json();
        const camera = data.camera, session = data.latest_session || {};
        document.getElementById('dot').className = camera.stream_available ? 'dot ok' : 'dot';
        document.getElementById('health').textContent = camera.stream_available ? 'Camera healthy' : (camera.error || 'Waiting for camera...');
        document.getElementById('fps').textContent = camera.fps == null ? '—' : camera.fps.toFixed(2);
        document.getElementById('age').textContent = camera.last_frame_age_sec == null ? '—' : camera.last_frame_age_sec.toFixed(2) + ' s';
        document.getElementById('observed').textContent = camera.received_frames;
        document.getElementById('session').textContent = session.session_id || '—';
        document.getElementById('status').textContent = session.status || '—';
        document.getElementById('size').textContent = formatBytes(session.bag_bytes);
      } catch (error) { document.getElementById('health').textContent = error.toString(); }
    }
    update(); setInterval(update, 1000);
  </script>
</body>
</html>
""".encode("utf-8")


def _start_ros(state: LiveCameraState) -> tuple[Any, threading.Thread] | None:
    try:
        import rclpy
        from rclpy.executors import ExternalShutdownException
        from rclpy.node import Node
        from rclpy.qos import qos_profile_sensor_data
        from rclpy.signals import SignalHandlerOptions
        from sensor_msgs.msg import CompressedImage
    except ImportError as error:
        state.error = f"ROS 2 Python modules unavailable: {error}"
        return None

    # Let the HTTP server's main thread own SIGINT/SIGTERM handling. Installing
    # rclpy's handler as well makes Ctrl-C shut down the same context twice on
    # ROS 2 Humble.
    rclpy.init(args=None, signal_handler_options=SignalHandlerOptions.NO)
    node = Node("duck_dataset_web_monitor")

    def on_image(message: Any) -> None:
        payload = bytes(message.data)
        if payload:
            state.update(payload)

    node.create_subscription(
        CompressedImage, state.topic, on_image, qos_profile_sensor_data
    )
    state.ros_available = True
    def spin_node() -> None:
        try:
            rclpy.spin(node)
        except ExternalShutdownException:
            pass

    thread = threading.Thread(target=spin_node, daemon=True)
    thread.start()
    return (node, thread)


def serve_dataset(*, root: Path, bind_address: str, port: int, topic: str) -> None:
    root = root.expanduser().resolve()
    build_dataset_index(root)
    state = LiveCameraState(topic)
    ros_runtime = _start_ros(state)

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(root), **kwargs)

        def _send_bytes(self, payload: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            path = urlsplit(self.path).path
            if path == "/live":
                self._send_bytes(_live_page(), "text/html; charset=utf-8")
                return
            if path == "/api/live":
                payload = {
                    "camera": state.snapshot(),
                    "latest_session": _latest_session(root),
                }
                self._send_bytes(
                    json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8",
                )
                return
            if path == "/stream.mjpg":
                self.send_response(200)
                self.send_header(
                    "Content-Type", "multipart/x-mixed-replace; boundary=frame"
                )
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                last_sequence = -1
                try:
                    while True:
                        with state.condition:
                            state.condition.wait_for(
                                lambda: state.sequence != last_sequence, timeout=3.0
                            )
                            if state.jpeg is None or state.sequence == last_sequence:
                                continue
                            jpeg = state.jpeg
                            last_sequence = state.sequence
                        self.wfile.write(b"--frame\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n")
                        self.wfile.write(
                            f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii")
                        )
                        self.wfile.write(jpeg)
                        self.wfile.write(b"\r\n")
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            if path == "/":
                build_dataset_index(root)
            super().do_GET()

    class DatasetHTTPServer(ThreadingHTTPServer):
        # A browser keeps the MJPEG request open. Daemon request threads let
        # Ctrl-C stop the server immediately even while /stream.mjpg is open.
        daemon_threads = True
        allow_reuse_address = True

    server = DatasetHTTPServer((bind_address, port), Handler)
    print(f"Dataset browser: http://{bind_address}:{port}/", flush=True)
    print(f"Live monitor:   http://{bind_address}:{port}/live", flush=True)
    print(f"Camera topic:   {topic}", flush=True)
    print(f"Serving:        {root}", flush=True)
    print("Press Ctrl-C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if ros_runtime is not None:
            import rclpy

            node, thread = ros_runtime
            if rclpy.ok():
                rclpy.shutdown()
            thread.join(timeout=2.0)
            node.destroy_node()
