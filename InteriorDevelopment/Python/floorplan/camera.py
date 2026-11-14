"""Camera geometry.

World frame: x = east, y = north, z = up (metres).
A camera looks along `forward`; `right` is the right-hand side of the picture and `up` the top of it.

OpenCV's camera frame is x right, y DOWN, z forward, so helper functions below convert between the two.
"""

import math

import numpy as np


def intrinsics(width: int, height: int, fov_long_side_deg: float) -> tuple[float, float, float]:
    """Focal length in pixels and the picture centre, assuming square pixels and no distortion."""
    focal = (max(width, height) / 2.0) / math.tan(math.radians(fov_long_side_deg) / 2.0)
    return focal, width / 2.0, height / 2.0


def camera_matrix(width: int, height: int, fov_long_side_deg: float) -> np.ndarray:
    focal, cx, cy = intrinsics(width, height, fov_long_side_deg)
    return np.array([[focal, 0, cx], [0, focal, cy], [0, 0, 1]], dtype=np.float64)


def camera_axes(heading_deg: float, pitch_deg: float, roll_deg: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(right, up, forward) as world vectors.

    heading: clockwise from north. pitch: positive looks up. roll: positive when the right side is higher.
    """
    h, p, r = math.radians(heading_deg), math.radians(pitch_deg), math.radians(roll_deg)
    forward = np.array([math.cos(p) * math.sin(h), math.cos(p) * math.cos(h), math.sin(p)])
    right0 = np.array([math.cos(h), -math.sin(h), 0.0])
    up0 = np.cross(right0, forward)
    right = right0 * math.cos(r) + up0 * math.sin(r)
    up = up0 * math.cos(r) - right0 * math.sin(r)
    return right, up, forward


def cv_to_world(vector_cv: np.ndarray, axes: tuple[np.ndarray, np.ndarray, np.ndarray]) -> np.ndarray:
    """A vector in OpenCV camera coordinates (x right, y down, z forward) as a world vector."""
    right, up, forward = axes
    return vector_cv[0] * right + (-vector_cv[1]) * up + vector_cv[2] * forward


def heading_of(vector_world: np.ndarray) -> float:
    """Compass heading (degrees clockwise from north, 0 to 360) of the horizontal part of a vector."""
    return math.degrees(math.atan2(vector_world[0], vector_world[1])) % 360.0


def pixels_to_world(
    u: np.ndarray, v: np.ndarray, depth: np.ndarray,
    focal: float, cx: float, cy: float,
    axes: tuple[np.ndarray, np.ndarray, np.ndarray], position: np.ndarray,
) -> np.ndarray:
    """Pixel columns/rows plus depth along the viewing direction -> world points, shape (..., 3)."""
    right, up, forward = axes
    x_right = depth * (u - cx) / focal
    y_up = -depth * (v - cy) / focal
    return (
        position
        + x_right[..., None] * right
        + y_up[..., None] * up
        + depth[..., None] * forward
    )
