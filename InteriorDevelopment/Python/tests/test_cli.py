"""The command line."""

import json

import numpy as np
from PIL import Image

from floorplan.__main__ import main


def test_inspect_summarises_the_photos(tmp_path, capsys):
    session = tmp_path / "20261114-031542-k3x9"
    session.mkdir()
    for seq in range(3):
        stem = f"{seq:04d} 53.5 -113.5 10"
        Image.fromarray(np.zeros((8, 8, 3), np.uint8)).save(session / f"{stem}.jpg")
        (session / f"{stem}.json").write_text(json.dumps({
            "seq": seq, "takenAt": f"2026-11-14T03:00:0{seq * 2}Z", "latitude": 53.5, "longitude": -113.5,
            "headingDeg": 10, "gpsAccuracyM": 9}))
    main(["inspect", "--pictures", str(tmp_path)])
    out = capsys.readouterr().out
    assert "3 photos in 1 walk(s)" in out and "20261114-031542-k3x9" in out and "median accuracy 9 m" in out


def test_inspect_with_an_empty_folder(tmp_path, capsys):
    main(["inspect", "--pictures", str(tmp_path)])
    assert "No photos found" in capsys.readouterr().out


def test_demo_makes_a_floor_plan(tmp_path, capsys):
    main(["demo", "--out", str(tmp_path)])
    assert (tmp_path / "demo" / "floorplan.png").exists()
    assert "Detected walls span" in capsys.readouterr().out