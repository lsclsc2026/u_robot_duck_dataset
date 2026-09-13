from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import build_model_validation_set as validation_set  # noqa: E402


class ValidationSetTest(unittest.TestCase):
    def _metric(self, index: int, blur: float = 100.0):
        record = {
            "index": index,
            "filename": f"{index:06d}.jpg",
            "relative_sec": float(index),
            "sha256": "0" * 64,
        }
        return validation_set.FrameMetric(
            session_id="session",
            session_dir=Path("/tmp/session"),
            record=record,
            source_path=Path(f"/tmp/{index:06d}.jpg"),
            blur_score=blur,
            brightness=100.0,
            perceptual_hash=f"{index:016x}",
        )

    def test_split_sessions_are_disjoint(self) -> None:
        calibration = {
            item[0] for item in validation_set.GROUNDING_SPLITS["calibration"]
        }
        holdout = {item[0] for item in validation_set.GROUNDING_SPLITS["holdout"]}
        self.assertFalse(calibration & holdout)
        self.assertEqual(
            sum(item[1] for item in validation_set.GROUNDING_SPLITS["calibration"]),
            100,
        )
        self.assertEqual(
            sum(item[1] for item in validation_set.GROUNDING_SPLITS["holdout"]),
            60,
        )

    def test_selection_has_exact_count_and_temporal_coverage(self) -> None:
        candidates = [self._metric(index, float(index + 1)) for index in range(100)]
        selected = validation_set._select_metrics(candidates, 20)
        self.assertEqual(len(selected), 20)
        indices = [int(item.record["index"]) for item in selected]
        self.assertEqual(indices, sorted(indices))
        self.assertLess(indices[0], 5)
        self.assertGreaterEqual(indices[-1], 95)

    def test_clip_range_is_half_open_and_monotonic(self) -> None:
        records = [
            {"index": index, "relative_sec": index / 10}
            for index in range(100)
        ]
        selected = validation_set._records_for_clip(records, 2.0, 5.0)
        self.assertEqual(len(selected), 30)
        self.assertEqual(selected[0]["relative_sec"], 2.0)
        self.assertEqual(selected[-1]["relative_sec"], 4.9)

    def test_dhash_is_stable(self) -> None:
        image = np.tile(np.arange(32, dtype=np.uint8), (32, 1))
        self.assertEqual(validation_set._dhash(image), validation_set._dhash(image))
        self.assertEqual(len(validation_set._dhash(image)), 16)

    def test_output_is_sibling_of_sessions(self) -> None:
        root = Path("/tmp/example_dataset")
        output = validation_set._benchmark_output(root)
        validation_set._assert_safe_output(root, output)
        self.assertEqual(output.parent, root / "benchmarks")


if __name__ == "__main__":
    unittest.main()
