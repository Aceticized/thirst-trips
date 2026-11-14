"""A pretend building, used by the tests and by `python -m floorplan demo`.

It renders what a phone would see inside a rectangular room: a picture with texture (so feature matching has
something to grab), the true depth, and the true labels. That makes it possible to check the whole pipeline
(including the visual position correction) without downloading any neural network.
"""

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.ndimage import gaussian_filter

from .camera import camera_axes, intrinsics
from .dataset import Frame
from .geo import LocalFrame
from .models import label_ids_from

# Same ids and names as the real ADE20K label set, so the code treats fake and real alike.
ID2LABEL = {0: "wall", 3: "floor, flooring", 5: "ceiling", 8: "windowpane, window", 12: "person, individual"}
WALL, FLOOR, CEILING = 0, 3, 5


def _texture(rng: np.random.Generator, size: int = 256) -> np.ndarray:
    coarse = gaussian_filter(rng.random((size, size)), 6)
    fine = gaussian_filter(rng.random((size, size)), 1.2)
    tex = 0.55 * (coarse - coarse.min()) / np.ptp(coarse) + 0.45 * (fine - fine.min()) / np.ptp(fine)
    for _ in range(14):  # random "posters" give strong corners
        x, y = rng.integers(0, size - 40, 2)
        tex[y:y + rng.integers(10, 40), x:x + rng.integers(10, 40)] = rng.random()
    return tex


@dataclass
class Room:
    """A box from (0, 0) to (width, depth) metres, `height` tall, floor at z = 0."""
    width: float = 6.0
    depth: float = 4.0
    height: float = 2.8
    seed: int = 7
    textures: dict = field(default_factory=dict)

    def __post_init__(self):
        rng = np.random.default_rng(self.seed)
        for key in ("west", "east", "south", "north", "floor", "ceiling"):
            self.textures[key] = _texture(rng)

    def render(self, position, heading_deg, pitch_deg, roll_deg, width, height, fov_long_side_deg):
        """Returns (rgb uint8 image, depth along the optical axis in metres, label ids)."""
        focal, cx, cy = intrinsics(width, height, fov_long_side_deg)
        right, up, forward = camera_axes(heading_deg, pitch_deg, roll_deg)
        u, v = np.meshgrid(np.arange(width) + 0.5, np.arange(height) + 0.5)
        rays = (
            ((u - cx) / focal)[..., None] * right
            + (-(v - cy) / focal)[..., None] * up
            + forward
        )  # z component along `forward` is exactly 1, so t is already the depth along the optical axis
        origin = np.asarray(position, dtype=np.float64)

        planes = [  # (axis, value, texture key, label)
            (0, 0.0, "west", WALL), (0, self.width, "east", WALL),
            (1, 0.0, "south", WALL), (1, self.depth, "north", WALL),
            (2, 0.0, "floor", FLOOR), (2, self.height, "ceiling", CEILING),
        ]
        best_t = np.full((height, width), np.inf)
        label = np.zeros((height, width), dtype=np.int32)
        brightness = np.zeros((height, width))
        for axis, value, key, plane_label in planes:
            with np.errstate(divide="ignore", invalid="ignore"):
                t = (value - origin[axis]) / rays[..., axis]
            hit = origin + t[..., None] * rays
            other = [a for a in range(3) if a != axis]
            inside = (
                (t > 0)
                & (hit[..., other[0]] >= -1e-6) & (hit[..., other[0]] <= (self.width, self.depth, self.height)[other[0]] + 1e-6)
                & (hit[..., other[1]] >= -1e-6) & (hit[..., other[1]] <= (self.width, self.depth, self.height)[other[1]] + 1e-6)
            )
            closer = inside & (t < best_t)
            tex = self.textures[key]
            tu = (hit[..., other[0]] * 50).astype(int) % tex.shape[1]
            tv = (hit[..., other[1]] * 50).astype(int) % tex.shape[0]
            brightness = np.where(closer, tex[tv, tu], brightness)
            label = np.where(closer, plane_label, label)
            best_t = np.where(closer, t, best_t)

        depth = np.where(np.isfinite(best_t), best_t, 0.0).astype(np.float32)
        gray = (np.clip(brightness, 0, 1) * 200 + 30).astype(np.uint8)
        return np.dstack([gray, gray, gray]), depth, label


class FakeDepth:
    """Looks up the true depth for a frame (the frame knows which synthetic photo it is)."""

    model_name = "synthetic-depth"

    def __init__(self, truth: dict):
        self.truth = truth

    def predict(self, image, frame):
        return self.truth[frame.path.name][1]


class FakeSegmenter:
    model_name = "synthetic-segmentation"

    def __init__(self, truth: dict):
        self.truth = truth
        self.id2label = ID2LABEL

    def predict(self, image, frame):
        return self.truth[frame.path.name][2]

    def label_ids(self, names):
        return label_ids_from(self.id2label, names)


def walk_room(room: Room, local: LocalFrame, waypoints, step_m: float = 0.9, size=(240, 320), fov=70.0,
              gps_noise_m: float = 0.0, compass_noise_deg: float = 0.0, seed: int = 3, camera_height: float = 1.4):
    """Walk through the room along `waypoints` (x, y) taking a photo every `step_m` metres, looking along the
    walk but swinging the camera left and right. Returns (frames, truth dict, true poses).

    The room's (0, 0) corner is the local origin (east, north). Noise is added to the saved GPS/compass only.
    """
    rng = np.random.default_rng(seed)
    height, width = size
    positions, headings = [], []
    for a, b in zip(waypoints[:-1], waypoints[1:]):
        a, b = np.array(a, float), np.array(b, float)
        length = np.linalg.norm(b - a)
        heading = math.degrees(math.atan2(b[0] - a[0], b[1] - a[1]))
        for k in range(max(1, int(length // step_m))):
            positions.append(a + (b - a) * (k * step_m / length))
            headings.append(heading)

    frames, truth, poses = [], {}, []
    import tempfile
    from pathlib import Path
    from PIL import Image

    folder = Path(tempfile.mkdtemp(prefix="floorplan-synthetic-"))
    for i, (p, base) in enumerate(zip(positions, headings)):
        swing = 28.0 * math.sin(i * 1.3)
        heading = (base + swing) % 360.0
        pitch = 4.0 * math.sin(i * 0.7)
        roll = 2.0 * math.sin(i * 0.9)
        position = np.array([p[0], p[1], camera_height])
        image, depth, labels = room.render(position, heading, pitch, roll, width, height, fov)
        name = f"{i:04d}.jpg"
        Image.fromarray(image).save(folder / name, quality=95)
        truth[name] = (image, depth, labels)
        poses.append((position, heading, pitch, roll))

        noisy_xy = p + rng.normal(0, gps_noise_m, 2)
        lat, lon = local.to_latlon(float(noisy_xy[0]), float(noisy_xy[1]))
        frames.append(Frame(
            path=folder / name, session="synthetic", seq=i, taken_at=1.0e9 + 2.0 * i,
            latitude=lat, longitude=lon, gps_accuracy_m=max(gps_noise_m * 2, 3.0),
            heading_deg=(heading + rng.normal(0, compass_noise_deg)) % 360.0,
            pitch_deg=pitch, roll_deg=roll, fov_long_side_deg=fov, has_description=True,
        ))
    return frames, truth, poses
