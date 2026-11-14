"""Small pieces: reading the photo folder, geometry helpers."""

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

from floorplan.camera import camera_axes, cv_to_world, heading_of, intrinsics, pixels_to_world
from floorplan.dataset import load_frames
from floorplan.geo import LocalFrame, wrap180
from floorplan.models import label_ids_from


def make_jpeg(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.zeros((8, 8, 3), np.uint8)).save(path)


def test_reads_new_style_photos_with_their_description(tmp_path):
    session = tmp_path / "20261114-031542-k3x9"
    make_jpeg(session / "0007 53.1023982 -113.2034985 349.jpg")
    (session / "0007 53.1023982 -113.2034985 349.json").write_text(json.dumps({
        "version": 1, "session": "20261114-031542-k3x9", "seq": 7, "takenAt": "2026-11-14T03:15:50.000Z",
        "latitude": 53.1023982, "longitude": -113.2034985, "gpsAccuracyM": 12.5, "headingDeg": 348.6,
        "pitchDeg": -4.2, "rollDeg": 1.5, "assumedFovLongSideDeg": 70,
    }))
    frames = load_frames(tmp_path)["20261114-031542-k3x9"]
    assert len(frames) == 1
    f = frames[0]
    assert f.seq == 7 and f.has_description
    assert (f.latitude, f.longitude) == (53.1023982, -113.2034985)
    assert f.heading_deg == 348.6 and f.pitch_deg == -4.2 and f.roll_deg == 1.5 and f.gps_accuracy_m == 12.5


def test_reads_old_style_photos_from_the_file_name_alone(tmp_path):
    make_jpeg(tmp_path / "53.1023982 -113.2034985 349.jpg")
    make_jpeg(tmp_path / "53.1023982 -113.2034985 349 (2).jpg")
    make_jpeg(tmp_path / "holiday.jpg")  # not ours: ignored
    frames = load_frames(tmp_path)["loose-photos"]
    assert len(frames) == 2
    assert all(not f.has_description and f.heading_deg == 349 for f in frames)


def test_broken_description_falls_back_to_the_name(tmp_path):
    session = tmp_path / "20261114-031542-k3x9"
    make_jpeg(session / "0001 53.5 -113.5 10.jpg")
    (session / "0001 53.5 -113.5 10.json").write_text("{not json")
    frame = load_frames(tmp_path)["20261114-031542-k3x9"][0]
    assert not frame.has_description and frame.heading_deg == 10 and frame.seq == 1


def test_photos_come_back_in_the_order_taken(tmp_path):
    session = tmp_path / "20261114-031542-k3x9"
    for seq, taken in [(2, "03:00:04"), (0, "03:00:00"), (1, "03:00:02")]:
        stem = f"{seq:04d} 53.5 -113.5 10"
        make_jpeg(session / f"{stem}.jpg")
        (session / f"{stem}.json").write_text(json.dumps({
            "seq": seq, "takenAt": f"2026-11-14T{taken}Z", "latitude": 53.5, "longitude": -113.5, "headingDeg": 10}))
    assert [f.seq for f in load_frames(tmp_path)["20261114-031542-k3x9"]] == [0, 1, 2]


def test_local_frame_round_trip_and_scale():
    local = LocalFrame(53.5, -113.5)
    x, y = local.to_local(53.5009, -113.5)          # 0.0009 degrees north is about 100 m
    assert abs(x) < 1e-6 and 99 < y < 101
    lat, lon = local.to_latlon(*local.to_local(53.5123, -113.4876))
    assert abs(lat - 53.5123) < 1e-9 and abs(lon + 113.4876) < 1e-9


def test_wrap180():
    assert wrap180(190) == -170 and wrap180(-190) == 170 and wrap180(10) == 10


def test_camera_axes_follow_the_compass():
    right, up, forward = camera_axes(0, 0, 0)       # facing north
    assert np.allclose(forward, [0, 1, 0]) and np.allclose(right, [1, 0, 0]) and np.allclose(up, [0, 0, 1])
    right, up, forward = camera_axes(90, 0, 0)      # facing east: right-hand side is south
    assert np.allclose(forward, [1, 0, 0]) and np.allclose(right, [0, -1, 0])
    assert abs(heading_of(forward) - 90) < 1e-9


def test_pitch_and_roll_signs():
    _, _, forward = camera_axes(0, 30, 0)
    assert forward[2] > 0                            # positive pitch looks up
    right, _, _ = camera_axes(0, 0, 10)
    assert right[2] > 0                              # positive roll lifts the right-hand side


def test_axes_are_perpendicular_unit_vectors():
    for h, p, r in [(10, 5, -3), (200, -20, 15), (359, 60, 0)]:
        right, up, forward = camera_axes(h, p, r)
        for v in (right, up, forward):
            assert abs(np.linalg.norm(v) - 1) < 1e-9
        assert abs(right @ up) < 1e-9 and abs(right @ forward) < 1e-9 and abs(up @ forward) < 1e-9


def test_centre_pixel_looks_straight_ahead():
    focal, cx, cy = intrinsics(320, 240, 70)
    axes = camera_axes(90, 0, 0)
    point = pixels_to_world(np.array([cx]), np.array([cy]), np.array([4.0]), focal, cx, cy, axes, np.array([1.0, 2.0, 1.4]))
    assert np.allclose(point[0], [5.0, 2.0, 1.4])    # 4 m east of the camera, same height


def test_opencv_frame_conversion():
    axes = camera_axes(0, 0, 0)
    assert np.allclose(cv_to_world(np.array([0, 0, 1.0]), axes), [0, 1, 0])      # forward
    assert np.allclose(cv_to_world(np.array([1.0, 0, 0]), axes), [1, 0, 0])      # right
    assert np.allclose(cv_to_world(np.array([0, 1.0, 0]), axes), [0, 0, -1])     # OpenCV y points down


def test_label_names_match_on_the_first_word():
    ids = label_ids_from({0: "wall", 3: "floor, flooring", 8: "windowpane, window", 28: "rug, carpet, carpeting"},
                         ("wall", "floor"))
    assert ids == {0, 3}
