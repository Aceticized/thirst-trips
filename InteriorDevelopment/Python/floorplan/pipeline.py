"""Runs every stage, from the folder of photos to the finished floor plan."""

import csv
import json
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from . import render
from .camera import camera_axes, camera_matrix
from .config import Settings
from .dataset import Frame, load_frames
from .geo import LocalFrame
from .occupancy import OccupancyGrid
from .poses import Pose, baseline_poses, refine_poses
from .scan import Scan, frame_to_scan
from .visual_odometry import relative_motion
from .walls import Segment, extract_walls


@dataclass
class BuildResult:
    grid: OccupancyGrid
    walls: list[Segment]
    poses: dict[str, list[Pose]]
    frames: dict[str, list[Frame]]
    out_dir: Path


class FrameData:
    """Loads a photo's picture, depth and labels on demand and remembers the last few (and caches to disk)."""

    def __init__(self, depth, segmenter, cache_dir: Path | None, settings: Settings, keep: int = 4):
        self.depth, self.segmenter, self.cache_dir, self.settings, self.keep = depth, segmenter, cache_dir, settings, keep
        self._memory: OrderedDict[str, tuple] = OrderedDict()
        self._signature = json.dumps({
            "depth": getattr(depth, "model_name", type(depth).__name__),
            "segmentation": getattr(segmenter, "model_name", type(segmenter).__name__),
        })

    def get(self, frame: Frame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(rgb picture, depth in metres before depth_scale, label ids)"""
        key = str(frame.path)
        if key in self._memory:
            self._memory.move_to_end(key)
            return self._memory[key]
        image = Image.open(frame.path).convert("RGB")
        picture = np.asarray(image)
        depth, labels = self._cached(frame)
        if depth is None:
            depth = np.asarray(self.depth.predict(image, frame), dtype=np.float32)
            labels = np.asarray(self.segmenter.predict(image, frame), dtype=np.int32)
            self._store(frame, depth, labels)
        self._memory[key] = (picture, depth, labels)
        while len(self._memory) > self.keep:
            self._memory.popitem(last=False)
        return self._memory[key]

    def _cache_file(self, frame: Frame) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / frame.session / f"{frame.stem}.npz"

    def _cached(self, frame: Frame):
        file = self._cache_file(frame)
        if file is None or not file.exists():
            return None, None
        try:
            with np.load(file, allow_pickle=False) as data:
                if str(data["signature"]) != self._signature:
                    return None, None
                return data["depth"].astype(np.float32), data["labels"].astype(np.int32)
        except (OSError, ValueError, KeyError):
            return None, None

    def _store(self, frame: Frame, depth: np.ndarray, labels: np.ndarray) -> None:
        file = self._cache_file(frame)
        if file is None:
            return
        file.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(file, depth=depth.astype(np.float16), labels=labels.astype(np.int16),
                            signature=np.array(self._signature))


def _fov(frame: Frame, settings: Settings) -> float:
    return settings.fov_long_side_deg if settings.fov_long_side_deg else frame.fov_long_side_deg


def _motions(frames: list[Frame], data: FrameData, settings: Settings, log) -> list:
    """(i, j, how the camera moved from photo i to photo j) for every pair that could be measured.

    Each photo is first compared with the next one; if that fails (a sharp turn, a blank wall), the photos
    after it are tried instead, up to three photos ahead.
    """
    motions = []
    for i in range(len(frames) - 1):
        a = frames[i]
        picture_a, depth_a, _ = data.get(a)
        height, width = depth_a.shape
        matrix = camera_matrix(width, height, _fov(a, settings))
        for j in range(i + 1, min(i + 4, len(frames))):
            b = frames[j]
            if b.taken_at - a.taken_at > settings.max_gap_seconds:
                break
            picture_b, _, _ = data.get(b)
            motion = relative_motion(
                picture_a, depth_a * settings.depth_scale, picture_b, matrix,
                min_inliers=settings.vo_min_inliers, min_depth=settings.min_depth_m, max_depth=settings.max_depth_m,
            )
            usable = motion is not None and (
                not motion.candidates or motion.inliers / motion.candidates >= settings.vo_min_inlier_ratio
            )
            if usable:
                motions.append((i, j, motion))
                break
    log(f"    measured the camera movement between {len(motions)} of {len(frames) - 1} photo pairs")
    return motions

def build(
    pictures_dir: Path, out_dir: Path, settings: Settings, depth, segmenter,
    only_session: str | None = None, log=print,
) -> BuildResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    sessions = load_frames(pictures_dir)
    if only_session:
        sessions = {k: v for k, v in sessions.items() if k == only_session}
    sessions = {k: v for k, v in sessions.items() if v}
    if not sessions:
        raise SystemExit(f"No photos found in {pictures_dir}" + (f" for walk '{only_session}'" if only_session else ""))

    all_frames = [f for frames in sessions.values() for f in frames]
    local = LocalFrame(float(np.mean([f.latitude for f in all_frames])), float(np.mean([f.longitude for f in all_frames])))
    data = FrameData(depth, segmenter, out_dir / "cache", settings)
    log(f"{len(all_frames)} photos in {len(sessions)} walk(s); origin {local.lat0:.7f}, {local.lon0:.7f}")

    scans: list[Scan] = []
    all_poses: dict[str, list[Pose]] = {}
    for name, frames in sessions.items():
        log(f"  walk {name}: {len(frames)} photos")
        poses = baseline_poses(frames, local, settings)
        if settings.refine_poses and len(frames) > 1:
            poses = refine_poses(frames, poses, _motions(frames, data, settings, log), settings)
        all_poses[name] = poses
        for frame, pose in zip(frames, poses):
            _, depth_map, labels = data.get(frame)
            axes = camera_axes(pose.heading_deg, pose.pitch_deg, pose.roll_deg)
            scans.append(frame_to_scan(depth_map, labels, segmenter, axes, pose.position, _fov(frame, settings), settings))

    grid = OccupancyGrid.covering(scans, settings)
    for scan in scans:
        grid.add_scan(scan)
    walls = extract_walls(grid, settings)
    log(f"found {len(walls)} wall segments")

    path_xy = np.array([[p.x, p.y] for poses in all_poses.values() for p in poses])
    np.save(out_dir / "occupancy_log_odds.npy", grid.log_odds)
    render.save_debug_picture(grid, walls, path_xy, out_dir / "floorplan_debug.png")
    render.save_clean_plan(grid, walls, out_dir / "floorplan.png")
    render.save_svg(grid, walls, out_dir / "floorplan.svg")
    render.save_json(grid, walls, (local.lat0, local.lon0), {"settings": settings.to_dict()}, out_dir / "floorplan.json")
    with open(out_dir / "poses.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["walk", "photo", "x_m", "y_m", "heading_deg", "pitch_deg", "roll_deg"])
        for name, frames in sessions.items():
            for frame, pose in zip(frames, all_poses[name]):
                writer.writerow([name, frame.path.name, round(pose.x, 3), round(pose.y, 3),
                                 round(pose.heading_deg, 1), round(pose.pitch_deg, 1), round(pose.roll_deg, 1)])
    log(f"saved to {out_dir}")
    return BuildResult(grid=grid, walls=walls, poses=all_poses, frames=sessions, out_dir=out_dir)
