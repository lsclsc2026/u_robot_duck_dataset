from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from u_robot_duck_dataset.session import (
    create_session,
    load_metadata,
    mark_record_failed,
    mark_recording,
    parse_presence,
)


class SessionTest(unittest.TestCase):
    def test_create_session_writes_expected_layout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = create_session(
                root=Path(directory),
                session_id="test_session",
                scene="测试房间",
                duck_present=True,
                duck_count=1,
                lighting="normal",
                distance_range="1-3m",
                occlusion="partial",
                notes="test",
                topic="/camera/front/image/compressed",
            )
            self.assertTrue((session / "session.yaml").is_file())
            self.assertTrue((session / "raw").is_dir())
            self.assertTrue((session / "frames").is_dir())
            self.assertTrue((session / "artifacts").is_dir())
            metadata = load_metadata(session)
            self.assertEqual(metadata["scene"], "测试房间")
            self.assertIs(metadata["duck"]["present"], True)

    def test_presence_parser(self) -> None:
        self.assertIs(parse_presence("true"), True)
        self.assertIs(parse_presence("false"), False)
        self.assertIsNone(parse_presence("unknown"))

    def test_negative_session_rejects_positive_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                create_session(
                    root=Path(directory),
                    session_id="bad_negative",
                    scene="room",
                    duck_present=False,
                    duck_count=1,
                    lighting="normal",
                    distance_range="unknown",
                    occlusion="none",
                    notes="",
                    topic="/camera/front/image/compressed",
                )

    def test_mark_record_failed_updates_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = create_session(
                root=Path(directory),
                session_id="failed_session",
                scene="room",
                duck_present=None,
                duck_count=None,
                lighting="unknown",
                distance_range="unknown",
                occlusion="unknown",
                notes="",
                topic="/camera/front/image/compressed",
            )
            mark_record_failed(session, "recorder status 137")
            metadata = load_metadata(session)
            self.assertEqual(metadata["status"], "record_failed")
            self.assertEqual(metadata["recording"]["status"], "error")
            self.assertIn("137", metadata["recording"]["failure_reason"])

    def test_mark_recording_updates_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = create_session(
                root=Path(directory),
                session_id="active_session",
                scene="room",
                duck_present=True,
                duck_count=1,
                lighting="normal",
                distance_range="1m",
                occlusion="none",
                notes="",
                topic="/camera/front/image/compressed",
            )
            bag = session / "raw" / "camera_bag"
            mark_recording(session, bag)
            metadata = load_metadata(session)
            self.assertEqual(metadata["status"], "recording")
            self.assertEqual(metadata["paths"]["bag"], "raw/camera_bag")
            self.assertEqual(metadata["recording"]["status"], "active")


if __name__ == "__main__":
    unittest.main()
