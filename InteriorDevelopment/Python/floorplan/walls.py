"""From the occupied cells of the grid to straight wall segments (in metres)."""

import math
from dataclasses import dataclass

import cv2
import numpy as np

from .config import Settings
from .occupancy import OccupancyGrid


@dataclass
class Segment:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def length(self) -> float:
        return math.hypot(self.x1 - self.x0, self.y1 - self.y0)

    @property
    def angle_deg(self) -> float:
        """Direction of the line, 0 to 180 degrees counter-clockwise from east."""
        return math.degrees(math.atan2(self.y1 - self.y0, self.x1 - self.x0)) % 180.0

    def to_list(self) -> list[float]:
        return [round(v, 3) for v in (self.x0, self.y0, self.x1, self.y1)]


def _clean_mask(grid: OccupancyGrid, settings: Settings) -> np.ndarray:
    mask = grid.occupied().astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    for label in range(1, count):
        if stats[label, cv2.CC_STAT_AREA] < settings.min_blob_cells:
            mask[labels == label] = 0
    return mask


def _hough_segments(grid: OccupancyGrid, settings: Settings) -> list[Segment]:
    mask = _clean_mask(grid, settings)
    image = np.flipud(mask) * 255          # image row 0 is the north edge
    lines = cv2.HoughLinesP(
        image, rho=1, theta=math.pi / 180, threshold=settings.hough_threshold,
        minLineLength=max(3, int(settings.min_wall_length_m / grid.cell)),
        maxLineGap=max(1, int(settings.max_wall_gap_m / grid.cell)),
    )
    if lines is None:
        return []
    segments = []
    for x0, y0, x1, y1 in np.asarray(lines).reshape(-1, 4):
        ax, ay = grid.cell_centre(x0, grid.ny - 1 - y0)
        bx, by = grid.cell_centre(x1, grid.ny - 1 - y1)
        segments.append(Segment(ax, ay, bx, by))
    return segments


def _try_merge(a: Segment, b: Segment, settings: Settings) -> Segment | None:
    """One segment covering both, if they lie on the same line and touch or nearly touch."""
    angle_difference = abs(a.angle_deg - b.angle_deg)
    angle_difference = min(angle_difference, 180.0 - angle_difference)
    if angle_difference > settings.merge_angle_deg:
        return None
    theta = math.radians((a.angle_deg + b.angle_deg) / 2.0 if abs(a.angle_deg - b.angle_deg) < 90 else a.angle_deg)
    direction = np.array([math.cos(theta), math.sin(theta)])
    normal = np.array([-direction[1], direction[0]])
    points = np.array([[a.x0, a.y0], [a.x1, a.y1], [b.x0, b.y0], [b.x1, b.y1]])
    offsets = points @ normal
    if abs(offsets[:2].mean() - offsets[2:].mean()) > settings.merge_offset_m:
        return None
    along = points @ direction
    a_range, b_range = sorted(along[:2]), sorted(along[2:])
    if max(a_range[0], b_range[0]) - min(a_range[1], b_range[1]) > settings.max_wall_gap_m:
        return None
    lo, hi = along.min(), along.max()
    centre_offset = offsets.mean()
    start = direction * lo + normal * centre_offset
    end = direction * hi + normal * centre_offset
    return Segment(float(start[0]), float(start[1]), float(end[0]), float(end[1]))


def merge_segments(segments: list[Segment], settings: Settings) -> list[Segment]:
    pending = sorted(segments, key=lambda s: -s.length)
    merged: list[Segment] = []
    changed = True
    while changed:
        changed = False
        merged = []
        for segment in pending:
            for i, existing in enumerate(merged):
                combined = _try_merge(existing, segment, settings)
                if combined is not None:
                    merged[i] = combined
                    changed = True
                    break
            else:
                merged.append(segment)
        pending = sorted(merged, key=lambda s: -s.length)
    return merged


def dominant_direction_deg(segments: list[Segment]) -> float | None:
    """The building's main wall direction (0 to 90 degrees), weighting long walls more."""
    if not segments:
        return None
    sin_sum = sum(s.length * math.sin(math.radians(4 * s.angle_deg)) for s in segments)
    cos_sum = sum(s.length * math.cos(math.radians(4 * s.angle_deg)) for s in segments)
    return (math.degrees(math.atan2(sin_sum, cos_sum)) / 4.0) % 90.0


def snap_to_axes(segments: list[Segment], settings: Settings) -> list[Segment]:
    base = dominant_direction_deg(segments)
    if base is None:
        return segments
    snapped = []
    for s in segments:
        relative = (s.angle_deg - base) % 90.0
        nearest = round((s.angle_deg - base) / 90.0)
        error = relative if relative < 45.0 else relative - 90.0
        if abs(error) > settings.snap_tolerance_deg:
            snapped.append(s)
            continue
        theta = math.radians(base + 90.0 * nearest)
        cx, cy = (s.x0 + s.x1) / 2.0, (s.y0 + s.y1) / 2.0
        half = s.length / 2.0
        snapped.append(Segment(cx - half * math.cos(theta), cy - half * math.sin(theta),
                               cx + half * math.cos(theta), cy + half * math.sin(theta)))
    return snapped


def extract_walls(grid: OccupancyGrid, settings: Settings) -> list[Segment]:
    segments = merge_segments(_hough_segments(grid, settings), settings)
    if settings.manhattan:
        segments = merge_segments(snap_to_axes(segments, settings), settings)
    return [s for s in segments if s.length >= settings.min_wall_length_m]
