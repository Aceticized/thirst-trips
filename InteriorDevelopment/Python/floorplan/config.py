"""Every tunable number in one place."""

import json
from dataclasses import dataclass, fields
from pathlib import Path

# Names from the ADE20K label set (the first word of each label, e.g. "floor, flooring" -> "floor").
WALL_LABELS = ("wall", "door", "windowpane", "column")
FLOOR_LABELS = ("floor", "rug")
IGNORE_LABELS = ("person",)  # never treated as wall or floor

CALIBRATION_FILE = Path(__file__).resolve().parent.parent / "calibration.json"


@dataclass
class Settings:
    # ----- models -----
    depth_model: str = "depth-anything/Depth-Anything-V2-Metric-Indoor-Large-hf"
    segmentation_model: str = "facebook/mask2former-swin-large-ade-semantic"
    device: str = "auto"                    # "auto", "cpu" or "cuda"

    # ----- camera -----
    fov_long_side_deg: float | None = None  # None: use the value saved with each photo (a guess of 70)
    camera_height_m: float = 1.4            # phone held at chest height; the floor is this far below it
    depth_scale: float = 1.0                # multiply every depth by this (see `calibrate-scale`)

    # ----- turning one photo into a scan -----
    min_depth_m: float = 0.3
    max_depth_m: float = 10.0
    pixel_stride: int = 6                   # use every Nth pixel in each direction
    min_obstacle_height_m: float = 0.25     # wall points must be at least this far above the floor...
    max_obstacle_height_m: float = 2.2      # ...and no higher than this
    scan_percentile: float = 15.0           # per image column, the wall point at this percentile of distance
    min_points_per_column: int = 3

    # ----- occupancy grid -----
    cell_size_m: float = 0.10
    padding_m: float = 1.0
    log_odds_free: float = 0.35
    log_odds_floor: float = 0.2
    log_odds_occupied: float = 1.2
    log_odds_min: float = -4.0
    log_odds_max: float = 6.0
    occupied_threshold: float = 0.8
    free_threshold: float = -0.8
    min_blob_cells: int = 4                 # ignore specks smaller than this

    # ----- camera poses -----
    pose_smoothing_window: int = 5          # frames (odd) used to smooth GPS and compass
    refine_poses: bool = True               # use consecutive photos to correct the GPS and compass
    max_gap_seconds: float = 10.0           # photos further apart than this are not linked
    vo_min_inliers: int = 30
    vo_min_inlier_ratio: float = 0.5        # inliers / tried matches; lower means a doubtful match
    vo_sigma_m: float = 0.30                # how much we trust a visual position step
    vo_sigma_yaw_deg: float = 3.0           # ... and a visual turn
    compass_sigma_deg: float = 15.0         # how much we trust the phone compass
    gps_min_sigma_m: float = 3.0
    walk_speed_mps: float = 1.4             # for the weak 'a person cannot jump' link between unmeasured neighbours

    # ----- walls -----
    hough_threshold: int = 12
    min_wall_length_m: float = 0.8
    max_wall_gap_m: float = 0.4
    merge_angle_deg: float = 5.0
    merge_offset_m: float = 0.2
    manhattan: bool = False                 # snap walls to the building's main directions
    snap_tolerance_deg: float = 12.0

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}


def load_saved_calibration() -> dict:
    """Values saved by `python -m floorplan calibrate-scale`."""
    if CALIBRATION_FILE.exists():
        try:
            return json.loads(CALIBRATION_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    return {}


def default_settings() -> Settings:
    settings = Settings()
    saved = load_saved_calibration()
    if isinstance(saved.get("depth_scale"), (int, float)) and saved["depth_scale"] > 0:
        settings.depth_scale = float(saved["depth_scale"])
    return settings
