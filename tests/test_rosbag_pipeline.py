from __future__ import annotations

import gc
import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

try:
    import rosbag2_py
    from rclpy.serialization import serialize_message
    from sensor_msgs.msg import CompressedImage

    ROS_AVAILABLE = True
except ImportError:
    ROS_AVAILABLE = False

from u_robot_duck_dataset.extract import extract_frames
from u_robot_duck_dataset.index import build_dataset_index
from u_robot_duck_dataset.session import create_session, mark_recorded
from u_robot_duck_dataset.validate import load_manifest, validate_session
from u_robot_duck_dataset.visualize import create_visualization


@unittest.skipUnless(ROS_AVAILABLE, "ROS 2 Python modules are not available")
class RosbagPipelineTest(unittest.TestCase):
    def _write_bag(self, bag_dir: Path, topic: str) -> list[bytes]:
        writer = rosbag2_py.SequentialWriter()
        writer.open(
            rosbag2_py.StorageOptions(uri=str(bag_dir), storage_id="sqlite3"),
            rosbag2_py.ConverterOptions("", ""),
        )
        writer.create_topic(
            rosbag2_py.TopicMetadata(
                name=topic,
                type="sensor_msgs/msg/CompressedImage",
                serialization_format="cdr",
            )
        )
        payloads: list[bytes] = []
        start_ns = 1_700_000_000_000_000_000
        for index in range(12):
            image = np.full((180, 320, 3), (40, 55, 70), dtype=np.uint8)
            cv2.circle(image, (40 + index * 18, 95), 24, (0, 225, 255), -1)
            cv2.putText(
                image,
                str(index),
                (8, 25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )
            success, encoded = cv2.imencode(
                ".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 82]
            )
            self.assertTrue(success)
            payload = encoded.tobytes()
            payloads.append(payload)
            timestamp_ns = start_ns + index * 100_000_000
            message = CompressedImage()
            message.header.stamp.sec = timestamp_ns // 1_000_000_000
            message.header.stamp.nanosec = timestamp_ns % 1_000_000_000
            message.header.frame_id = "camera_link"
            message.format = "jpeg"
            message.data = payload
            writer.write(topic, serialize_message(message), timestamp_ns)
        del writer
        gc.collect()
        return payloads

    def test_end_to_end_preserves_jpeg_payload_and_writes_visuals(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            topic = "/test/camera/image/compressed"
            session = create_session(
                root=root,
                session_id="synthetic_pipeline",
                scene="synthetic",
                duck_present=True,
                duck_count=1,
                lighting="synthetic",
                distance_range="unknown",
                occlusion="none",
                notes="integration test",
                topic=topic,
            )
            bag_dir = session / "raw" / "camera_bag"
            payloads = self._write_bag(bag_dir, topic)
            self.assertTrue((bag_dir / "metadata.yaml").is_file())
            mark_recorded(session, bag_dir)

            summary = extract_frames(session_dir=session)
            self.assertEqual(summary["extracted_frames"], 12)
            manifest = load_manifest(session)
            self.assertEqual(len(manifest), 12)
            self.assertEqual(
                (session / "frames" / "000000.jpg").read_bytes(), payloads[0]
            )

            validation = validate_session(session_dir=session)
            self.assertEqual(validation["status"], "ok")
            self.assertEqual(validation["frame_count"], 12)

            visualization = create_visualization(
                session_dir=session, sample_count=6, columns=3
            )
            self.assertTrue(Path(visualization["contact_sheet"]).is_file())
            self.assertTrue(Path(visualization["preview_video"]).is_file())
            self.assertTrue(Path(visualization["html_report"]).is_file())
            index = build_dataset_index(root)
            self.assertEqual(index["session_count"], 1)
            self.assertIn(
                "synthetic_pipeline", (root / "index.html").read_text(encoding="utf-8")
            )
            report = json.loads(
                (session / "artifacts" / "validation_report.json").read_text()
            )
            self.assertEqual(report["status"], "ok")


if __name__ == "__main__":
    unittest.main()
