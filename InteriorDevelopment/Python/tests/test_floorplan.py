"""The geometry and the whole pipeline, on a made-up room (no neural networks)."""

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from floorplan.camera import camera_axes, camera_matrix, cv_to_world, heading_of
from floorplan.config import Settings
from floorplan.geo import LocalFrame, wrap180
from floorplan.occupancy import OccupancyGrid
from floorplan.pipeline import FrameData, _motions, build
from floorplan.poses import baseline_poses, refine_poses
from floorplan.scan import frame_to_scan
from floorplan.synthetic import FakeDepth, FakeSegmenter, Room, walk_room
from floorplan.visual_odometry import relative_motion
from floorplan.walls import Segment, dominant_direction_deg, extract_walls, merge_segments, snap_to_axes

LOOP = [(1.0, 1.0), (5.0, 1.0), (5.0, 3.0), (1.0, 3.0), (1.0, 1.0)]
ORIGIN = LocalFrame(53.5260874, -113.5203733)


def room_scans(settings, truth, true_poses, segmenter):
    scans = []
    for (name, (_, depth, labels)), (position, heading, pitch, roll) in zip(truth.items(), true_poses):
        scans.append(frame_to_scan(depth, labels, segmenter, camera_axes(heading, pitch, roll), position, 70.0, settings))
    return scans


def test_perfect_poses_give_the_room_back():
    room = Room(width=6.0, depth=4.0)
    frames, truth, true_poses = walk_room(room, ORIGIN, LOOP, step_m=0.6)
    settings = Settings()
    scans = room_scans(settings, truth, true_poses, FakeSegmenter(truth))
    grid = OccupancyGrid.covering(scans, settings)
    for scan in scans:
        grid.add_scan(scan)
    walls = extract_walls(grid, settings)

    xs = [v for w in walls for v in (w.x0, w.x1)]
    ys = [v for w in walls for v in (w.y0, w.y1)]
    assert abs((max(xs) - min(xs)) - 6.0) < 0.3
    assert abs((max(ys) - min(ys)) - 4.0) < 0.3
    # the walls found should lie on the true walls x = 0, 6 and y = 0, 4
    for w in walls:
        for x, y in ((w.x0, w.y0), (w.x1, w.y1)):
            distance = min(abs(x - 0), abs(x - 6), abs(y - 0), abs(y - 4))
            assert distance < 0.25


def test_free_space_is_inside_the_room_and_walls_are_not_free():
    room = Room()
    _, truth, true_poses = walk_room(room, ORIGIN, LOOP, step_m=0.6)
    settings = Settings()
    scans = room_scans(settings, truth, true_poses, FakeSegmenter(truth))
    grid = OccupancyGrid.covering(scans, settings)
    for scan in scans:
        grid.add_scan(scan)
    free_cells = np.argwhere(grid.free())
    centres = np.array([grid.cell_centre(ix, iy) for iy, ix in free_cells])
    assert (centres[:, 0] > -0.25).all() and (centres[:, 0] < 6.25).all()
    assert (centres[:, 1] > -0.25).all() and (centres[:, 1] < 4.25).all()
    assert len(centres) > 100


def test_pixels_marked_as_person_are_ignored():
    room = Room()
    _, truth, true_poses = walk_room(room, ORIGIN, LOOP, step_m=0.6)
    segmenter = FakeSegmenter(truth)
    name, (_, depth, labels) = next(iter(truth.items()))
    position, heading, pitch, roll = true_poses[0]
    everyone = np.full_like(labels, 12)  # label 12 = person
    scan = frame_to_scan(depth, everyone, segmenter, camera_axes(heading, pitch, roll), position, 70.0, Settings())
    assert scan.empty


def test_merge_joins_collinear_pieces_and_keeps_separate_walls_apart():
    settings = Settings()
    pieces = [Segment(0, 0, 2, 0), Segment(2.1, 0.02, 4, 0.0), Segment(0, 3, 4, 3)]
    merged = merge_segments(pieces, settings)
    lengths = sorted(round(s.length, 1) for s in merged)
    assert lengths == [4.0, 4.0]


def test_snapping_straightens_slightly_crooked_walls():
    settings = Settings()
    crooked = [Segment(0, 0, 4, 0.3), Segment(4, 0.3, 3.8, 4.2)]
    snapped = snap_to_axes(crooked, settings)
    turn = (snapped[1].angle_deg - snapped[0].angle_deg) % 180.0
    assert abs(turn - 90.0) < 0.01                                   # now exactly square to each other
    assert all(abs(a.length - b.length) < 1e-6 for a, b in zip(snapped, crooked))
    far_off = [Segment(0, 0, 4, 2.0)]                                # a diagonal wall is left alone
    assert snap_to_axes(far_off + crooked, settings)[0].angle_deg == far_off[0].angle_deg

def test_visual_motion_matches_the_truth():
    room = Room()
    a = ((2.0, 1.5, 1.4), 20.0, 0.0, 0.0)
    b = ((2.5, 2.1, 1.4), 38.0, 2.0, 1.0)
    img_a, depth_a, _ = room.render(a[0], *a[1:], 320, 240, 70.0)
    img_b, _, _ = room.render(b[0], *b[1:], 320, 240, 70.0)
    motion = relative_motion(img_a, depth_a, img_b, camera_matrix(320, 240, 70.0), min_inliers=20)
    assert motion is not None
    axes_a = camera_axes(*a[1:])
    step = cv_to_world(-motion.rotation.T @ motion.translation, axes_a)
    assert np.allclose(step, np.array(b[0]) - np.array(a[0]), atol=0.08)
    assert abs(wrap180(heading_of(cv_to_world(motion.rotation[2, :], axes_a)) - b[1])) < 1.0


def test_refinement_beats_the_raw_gps_and_compass():
    room = Room()
    frames, truth, true_poses = walk_room(room, ORIGIN, LOOP, step_m=0.6, gps_noise_m=3.0, compass_noise_deg=8.0)
    settings = Settings()
    data = FrameData(FakeDepth(truth), FakeSegmenter(truth), None, settings)
    motions = _motions(frames, data, settings, lambda *_: None)
    base = baseline_poses(frames, ORIGIN, settings)
    refined = refine_poses(frames, base, motions, settings)

    true_xy = np.array([p[0][:2] for p in true_poses])
    true_heading = np.array([p[1] for p in true_poses])

    def position_error(poses):
        return np.linalg.norm(np.array([[p.x, p.y] for p in poses]) - true_xy, axis=1).mean()

    def heading_error(poses):
        return np.mean([abs(wrap180(p.heading_deg - h)) for p, h in zip(poses, true_heading)])

    assert heading_error(refined) < 0.8 * heading_error(base)
    assert position_error(refined) < 0.8 * position_error(base)


def test_a_wrong_visual_match_does_not_wreck_the_result():
    room = Room()
    frames, truth, true_poses = walk_room(room, ORIGIN, LOOP, step_m=0.6, gps_noise_m=2.0, compass_noise_deg=5.0)
    settings = Settings()
    data = FrameData(FakeDepth(truth), FakeSegmenter(truth), None, settings)
    motions = _motions(frames, data, settings, lambda *_: None)
    i, j, good = motions[3]
    from floorplan.visual_odometry import RelativeMotion
    bad_rotation, _ = __import__("cv2").Rodrigues(np.array([0.0, math.radians(120), 0.0]))
    motions[3] = (i, j, RelativeMotion(rotation=bad_rotation, translation=np.array([5.0, 0.0, 3.0]), inliers=200, candidates=220))
    base = baseline_poses(frames, ORIGIN, settings)
    refined = refine_poses(frames, base, motions, settings)
    true_heading = np.array([p[1] for p in true_poses])
    error = np.mean([abs(wrap180(p.heading_deg - h)) for p, h in zip(refined, true_heading)])
    base_error = np.mean([abs(wrap180(p.heading_deg - h)) for p, h in zip(base, true_heading)])
    assert error < base_error * 1.2


def write_walk_as_pictures(frames, folder: Path) -> None:
    session = folder / "20261114-031542-k3x9"
    session.mkdir(parents=True)
    import shutil
    for f in frames:
        stem = f"{f.seq:04d} {f.latitude:.7f} {f.longitude:.7f} {round(f.heading_deg) % 360}"
        shutil.copy(f.path, session / f"{stem}.jpg")
        (session / f"{stem}.json").write_text(json.dumps({
            "version": 1, "session": session.name, "seq": f.seq,
            "takenAt": datetime.fromtimestamp(f.taken_at, timezone.utc).isoformat(),
            "latitude": f.latitude, "longitude": f.longitude, "gpsAccuracyM": f.gps_accuracy_m,
            "headingDeg": f.heading_deg, "pitchDeg": f.pitch_deg, "rollDeg": f.roll_deg,
            "assumedFovLongSideDeg": f.fov_long_side_deg,
        }))


def test_whole_pipeline_from_a_folder_of_photos(tmp_path):
    room = Room(width=6.0, depth=4.0)
    frames, truth, _ = walk_room(room, ORIGIN, LOOP, step_m=0.6, gps_noise_m=1.0, compass_noise_deg=4.0)
    pictures = tmp_path / "Pictures"
    write_walk_as_pictures(frames, pictures)
    # the pipeline's fakes look photos up by file name, so key the truth by the saved names
    renamed = {}
    for f, (name, value) in zip(sorted(pictures.rglob("*.jpg")), truth.items()):
        renamed[f.name] = value
    out = tmp_path / "out"
    result = build(pictures, out, Settings(), FakeDepth(renamed), FakeSegmenter(renamed), log=lambda *_: None)

    for name in ("floorplan.png", "floorplan_debug.png", "floorplan.svg", "floorplan.json", "poses.csv"):
        assert (out / name).exists()
    data = json.loads((out / "floorplan.json").read_text())
    assert data["walls"] and data["units"] == "metres"
    xs = [v for w in result.walls for v in (w.x0, w.x1)]
    ys = [v for w in result.walls for v in (w.y0, w.y1)]
    refined_error = abs((max(xs) - min(xs)) - 6.0) + abs((max(ys) - min(ys)) - 4.0)
    assert refined_error < 2.0

    # the visual correction should make the plan clearly better than raw GPS and compass
    raw_settings = Settings()
    raw_settings.refine_poses = False
    raw = build(pictures, tmp_path / "raw", raw_settings, FakeDepth(renamed), FakeSegmenter(renamed), log=lambda *_: None)
    rx = [v for w in raw.walls for v in (w.x0, w.x1)]
    ry = [v for w in raw.walls for v in (w.y0, w.y1)]
    raw_error = abs((max(rx) - min(rx)) - 6.0) + abs((max(ry) - min(ry)) - 4.0)
    assert refined_error < 0.7 * raw_error
    # running it again uses the saved depth and labels instead of asking the models again
    calls = []

    class Counting(FakeDepth):
        def predict(self, image, frame):
            calls.append(frame.path.name)
            return super().predict(image, frame)

    build(pictures, out, Settings(), Counting(renamed), FakeSegmenter(renamed), log=lambda *_: None)
    assert calls == []


def test_asking_for_a_walk_that_does_not_exist_stops_with_a_message(tmp_path):
    import pytest
    with pytest.raises(SystemExit):
        build(tmp_path, tmp_path / "out", Settings(), None, None, only_session="nope", log=lambda *_: None)
