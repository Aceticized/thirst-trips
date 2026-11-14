"""One photo -> a "scan": where the walls are around the camera, like a cheap laser scanner.

For every column of the picture we look at the wall pixels, convert them to world points using their depth,
and keep the nearest one (a low percentile, so a single bad pixel does not decide). Each kept point is a ray
from the camera to a wall. The floor pixels additionally tell us which spots can be walked on.
"""

from dataclasses import dataclass

import numpy as np

from .camera import intrinsics, pixels_to_world
from .config import FLOOR_LABELS, IGNORE_LABELS, WALL_LABELS, Settings


@dataclass
class Scan:
    camera_xy: np.ndarray      # (2,) metres
    hits_xy: np.ndarray        # (n, 2) wall points, one per usable picture column
    floor_xy: np.ndarray       # (m, 2) points on the floor

    @property
    def empty(self) -> bool:
        return len(self.hits_xy) == 0 and len(self.floor_xy) == 0


def frame_to_scan(
    depth: np.ndarray,
    labels: np.ndarray,
    segmenter,
    axes,
    position: np.ndarray,
    fov_long_side_deg: float,
    settings: Settings,
) -> Scan:
    """position is the camera in world metres (x, y, z), with the floor at z = position[2] - camera height."""
    height, width = depth.shape
    focal, cx, cy = intrinsics(width, height, fov_long_side_deg)
    step = max(1, settings.pixel_stride)

    rows = np.arange(step // 2, height, step)
    cols = np.arange(step // 2, width, step)
    uu, vv = np.meshgrid(cols, rows)
    d = depth[vv, uu].astype(np.float64) * settings.depth_scale
    lab = labels[vv, uu]

    usable = np.isfinite(d) & (d > settings.min_depth_m) & (d < settings.max_depth_m)
    ignore = np.isin(lab, list(segmenter.label_ids(IGNORE_LABELS)))
    d = np.where(usable, d, 1.0)  # keep the maths finite; unusable pixels are masked out below

    world = pixels_to_world(uu.astype(np.float64), vv.astype(np.float64), d, focal, cx, cy, axes, position)
    above_floor = world[..., 2] - (position[2] - settings.camera_height_m)

    is_wall = np.isin(lab, list(segmenter.label_ids(WALL_LABELS))) & usable & ~ignore
    is_wall &= (above_floor > settings.min_obstacle_height_m) & (above_floor < settings.max_obstacle_height_m)
    is_floor = np.isin(lab, list(segmenter.label_ids(FLOOR_LABELS))) & usable & ~ignore & (np.abs(above_floor) < 0.35)

    horizontal = np.hypot(world[..., 0] - position[0], world[..., 1] - position[1])
    hits = []
    for column in range(world.shape[1]):
        rows_here = np.flatnonzero(is_wall[:, column])
        if len(rows_here) < settings.min_points_per_column:
            continue
        distances = horizontal[rows_here, column]
        order = np.argsort(distances)
        pick = rows_here[order[int(settings.scan_percentile / 100.0 * (len(order) - 1))]]
        hits.append(world[pick, column, :2])

    floor_points = world[is_floor][:, :2] if is_floor.any() else np.zeros((0, 2))
    return Scan(
        camera_xy=np.asarray(position[:2], dtype=np.float64),
        hits_xy=np.array(hits, dtype=np.float64).reshape(-1, 2),
        floor_xy=floor_points,
    )
