#!/usr/bin/env python3
"""Publish synthetic JPEG frames for recording-script integration tests."""

from __future__ import annotations

import argparse

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage


class MockCamera(Node):
    def __init__(self, topic: str, rate: float) -> None:
        super().__init__("duck_dataset_mock_camera")
        self._publisher = self.create_publisher(
            CompressedImage, topic, qos_profile_sensor_data
        )
        self._sequence = 0
        self._timer = self.create_timer(1.0 / rate, self._publish)

    def _publish(self) -> None:
        image = np.full((180, 320, 3), (40, 55, 70), dtype=np.uint8)
        x = 40 + (self._sequence * 9) % 240
        cv2.circle(image, (x, 100), 24, (0, 225, 255), -1)
        success, encoded = cv2.imencode(
            ".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 82]
        )
        if not success:
            raise RuntimeError("failed to encode synthetic camera frame")
        message = CompressedImage()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = "camera_link"
        message.format = "jpeg"
        message.data = encoded.tobytes()
        self._publisher.publish(message)
        self._sequence += 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default="/test/camera/image/compressed")
    parser.add_argument("--rate", type=float, default=15.0)
    arguments = parser.parse_args()
    if arguments.rate <= 0:
        parser.error("--rate must be positive")

    rclpy.init()
    node = MockCamera(arguments.topic, arguments.rate)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

