"""Where each photo was taken from, and which way the camera faced.

GPS indoors can be tens of metres off and the phone compass wanders near steel, so the raw numbers are only a
starting point. `baseline_poses` smooths them. `refine_poses` then uses how the camera moved between consecutive
photos (see visual_odometry) to remove the wobble: the compass is only trusted loosely, the visual turns tightly,
and GPS only anchors the whole walk to the map.

Both refinement steps are small linear least-squares problems:

    yaw:       minimise  sum (e_i / compass_sigma)^2  +  sum ((e_j - e_i - d_ij) / yaw_sigma)^2
    position:  minimise  sum |p_i - gps_i|^2 / gps_sigma_i^2  +  sum |p_j - p_i - step_ij|^2 / vo_sigma^2

where e_i is the correction added to photo i's compass heading and d_ij / step_ij are the visual measurements\nbetween photo i and a later photo j. A link that disagrees with the rest fades out (see _reweighted).
"""

import math
from dataclasses import dataclass

import numpy as np

from .camera import camera_axes, cv_to_world, heading_of
from .config import Settings
from .dataset import Frame
from .geo import LocalFrame, wrap180


@dataclass
class Pose:
    x: float
    y: float
    z: float
    heading_deg: float
    pitch_deg: float
    roll_deg: float

    @property
    def position(self) -> np.ndarray:
        return np.array([self.x, self.y, self.z])


def baseline_poses(frames: list[Frame], local: LocalFrame, settings: Settings) -> list[Pose]:
    """GPS (smoothed with a moving median) and compass (as measured: the camera is swung around quickly, so\n    averaging neighbouring headings would only blur them)."""
    xy = np.array([local.to_local(f.latitude, f.longitude) for f in frames], dtype=np.float64)
    headings = np.array([f.heading_deg for f in frames], dtype=np.float64)
    half = max(0, settings.pose_smoothing_window // 2)
    poses = []
    for i, frame in enumerate(frames):
        lo, hi = max(0, i - half), min(len(frames), i + half + 1)
        x, y = np.median(xy[lo:hi], axis=0)
        poses.append(Pose(
            x=float(x), y=float(y), z=settings.camera_height_m,
            heading_deg=float(headings[i]),
            pitch_deg=frame.pitch_deg, roll_deg=frame.roll_deg,
        ))
    return poses


def _reweighted(rows_fixed, rhs_fixed, rows_links, rhs_links, link_scale: float, rounds: int = 5) -> np.ndarray:
    """Least squares where a link that disagrees with everything else (a bad visual match) fades out.

    Each round re-solves with link weights 1 / (1 + (residual / (3 * scale))^2), a Cauchy-style weight.
    """
    weights = np.ones(len(rows_links))
    solution = None
    for _ in range(rounds if len(rows_links) else 1):
        rows = list(rows_fixed) + [r * w for r, w in zip(rows_links, weights)]
        rhs = list(rhs_fixed) + [b * w for b, w in zip(rhs_links, weights)]
        solution, *_ = np.linalg.lstsq(np.array(rows), np.array(rhs), rcond=None)
        if not len(rows_links):
            break
        residual = np.array([abs(r @ solution - b) for r, b in zip(rows_links, rhs_links)])
        weights = 1.0 / (1.0 + (residual / (3.0 * link_scale)) ** 2)
    return solution


def _solve_yaw(compass: np.ndarray, links: list[tuple[int, int, float]], settings: Settings) -> np.ndarray:
    """Corrections e_i (degrees) to add to the compass headings. A link (i, j, d) says e_j - e_i = d."""
    n = len(compass)
    w_compass = 1.0 / settings.compass_sigma_deg
    w_visual = 1.0 / settings.vo_sigma_yaw_deg
    fixed_rows = [np.eye(n)[i] * w_compass for i in range(n)]
    fixed_rhs = [0.0] * n
    link_rows, link_rhs = [], []
    for i, j, d in links:
        row = np.zeros(n)
        row[j], row[i] = w_visual, -w_visual
        link_rows.append(row)
        link_rhs.append(w_visual * d)
    return _reweighted(fixed_rows, fixed_rhs, link_rows, link_rhs, link_scale=1.0)


def _solve_positions(
    gps_xy: np.ndarray, gps_sigma: np.ndarray, links: list[tuple[int, int, np.ndarray, float]], settings: Settings
) -> np.ndarray:
    """Positions (n x 2) from smoothed GPS and the visual steps between photos. A link (i, j, s, sigma) says p_j - p_i = s, give or take sigma metres."""
    n = len(gps_xy)
    out = np.zeros((n, 2))
    for axis in (0, 1):
        fixed_rows = [np.eye(n)[i] / gps_sigma[i] for i in range(n)]
        fixed_rhs = [gps_xy[i, axis] / gps_sigma[i] for i in range(n)]
        link_rows, link_rhs = [], []
        for i, j, step, sigma in links:
            row = np.zeros(n)
            row[j], row[i] = 1.0 / sigma, -1.0 / sigma
            link_rows.append(row)
            link_rhs.append(step[axis] / sigma)
        out[:, axis] = _reweighted(fixed_rows, fixed_rhs, link_rows, link_rhs, link_scale=1.0)
    return out


def refine_poses(
    frames: list[Frame], poses: list[Pose], motions: list, settings: Settings
) -> list[Pose]:
    """motions is a list of (i, j, RelativeMotion): how the camera moved from photo i to photo j."""
    if len(frames) < 2 or not motions:
        return poses

    compass = np.array([p.heading_deg for p in poses])
    yaw_links, step_vectors = [], []
    max_turn_disagreement = 3.0 * math.sqrt(2.0) * settings.compass_sigma_deg
    for i, j, motion in motions:
        if motion.inliers < settings.vo_min_inliers:
            continue
        if motion.candidates and motion.inliers / motion.candidates < settings.vo_min_inlier_ratio:
            continue
        axes_a = camera_axes(poses[i].heading_deg, poses[i].pitch_deg, poses[i].roll_deg)
        # Where photo j's camera points, as the visual measurement sees it from photo i.
        heading_j_visual = heading_of(cv_to_world(motion.rotation[2, :], axes_a))
        disagreement = wrap180(heading_j_visual - compass[j])
        if abs(disagreement) > max_turn_disagreement:
            continue  # the visual turn and the compass turn cannot both be right even with a bad compass
        yaw_links.append((i, j, disagreement))
        # Where photo j's camera is, relative to photo i, before the yaw correction is known.
        centre_j = -motion.rotation.T @ motion.translation
        step_vectors.append((i, j, cv_to_world(centre_j, axes_a)[:2]))
    if not yaw_links:
        return poses

    correction = _solve_yaw(compass, yaw_links, settings)

    step_links = []
    for i, j, step in step_vectors:
        turn = math.radians(correction[i])  # rotating clockwise by the yaw correction
        step_links.append((i, j, np.array([
            step[0] * math.cos(turn) + step[1] * math.sin(turn),
            -step[0] * math.sin(turn) + step[1] * math.cos(turn),
        ]), settings.vo_sigma_m))

    # Where two neighbouring photos could not be measured (a sharp turn), a person still cannot jump across the
    # room in a couple of seconds. This weak link keeps such gaps from letting the two halves drift apart.
    measured = {(i, j) for i, j, _, _ in step_links}
    for i in range(len(frames) - 1):
        if (i, i + 1) in measured:
            continue
        seconds = max(frames[i + 1].taken_at - frames[i].taken_at, 0.5)
        step_links.append((i, i + 1, np.zeros(2), max(0.5, settings.walk_speed_mps * seconds / 2.0)))

    gps_xy = np.array([[p.x, p.y] for p in poses])
    gps_sigma = np.array([max(f.gps_accuracy_m, settings.gps_min_sigma_m) for f in frames])
    xy = _solve_positions(gps_xy, gps_sigma, step_links, settings)

    return [
        Pose(x=float(xy[i, 0]), y=float(xy[i, 1]), z=p.z, heading_deg=float((compass[i] + correction[i]) % 360.0),
             pitch_deg=p.pitch_deg, roll_deg=p.roll_deg)
        for i, p in enumerate(poses)
    ]