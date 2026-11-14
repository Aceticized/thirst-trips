"""Command line:  python -m floorplan <command> --help"""

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

from .config import CALIBRATION_FILE, Settings, default_settings

PYTHON_DIR = Path(__file__).resolve().parent.parent
DEFAULT_PICTURES = PYTHON_DIR.parent / "Pictures"
DEFAULT_OUTPUT = PYTHON_DIR / "output"


def _add_settings_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument("--depth-model", help="Hugging Face name of a metric depth model")
    parser.add_argument("--segmentation-model", help="Hugging Face name of a Mask2Former ADE20K model")
    parser.add_argument("--depth-scale", type=float, help="multiply all depths by this (see calibrate-scale)")
    parser.add_argument("--fov", type=float, help="camera field of view along the long side, degrees (default: 70)")
    parser.add_argument("--camera-height", type=float, help="metres from the floor to the phone (default 1.4)")
    parser.add_argument("--cell", type=float, help="grid cell size in metres (default 0.10)")
    parser.add_argument("--stride", type=int, help="use every Nth pixel (default 6; bigger is faster)")


def _settings_from(args) -> Settings:
    settings = default_settings()
    settings.device = args.device
    for option, field in [
        ("depth_model", "depth_model"), ("segmentation_model", "segmentation_model"),
        ("depth_scale", "depth_scale"), ("fov", "fov_long_side_deg"), ("camera_height", "camera_height_m"),
        ("cell", "cell_size_m"), ("stride", "pixel_stride"),
    ]:
        value = getattr(args, option, None)
        if value is not None:
            setattr(settings, field, value)
    if getattr(args, "no_refine", False):
        settings.refine_poses = False
    if getattr(args, "manhattan", False):
        settings.manhattan = True
    return settings


def _load_models(settings: Settings):
    try:
        from .models import DepthEstimator, SemanticSegmenter
        print(f"Loading depth model {settings.depth_model} ...")
        depth = DepthEstimator(settings.depth_model, settings.device)
        print(f"Loading segmentation model {settings.segmentation_model} ...")
        segmenter = SemanticSegmenter(settings.segmentation_model, settings.device)
    except ImportError as error:
        raise SystemExit(
            f"The AI libraries are not installed ({error}).\n"
            "Run:  pip install -r requirements-models.txt"
        )
    print(f"Models ready on {depth.device}.")
    return depth, segmenter


# ---------------------------------------------------------------------------------------------- build

def command_build(args) -> None:
    from .dataset import load_frames
    from .pipeline import build

    if not any(load_frames(Path(args.pictures)).values()):
        raise SystemExit(f"No photos found in {args.pictures}. Walk around with the navigator first (and say yes to sharing snapshots).")
    settings = _settings_from(args)
    depth, segmenter = _load_models(settings)
    build(Path(args.pictures), Path(args.out), settings, depth, segmenter, only_session=args.session)


# -------------------------------------------------------------------------------------------- inspect

def command_inspect(args) -> None:
    from .dataset import load_frames
    from .geo import LocalFrame

    sessions = load_frames(Path(args.pictures))
    if not sessions:
        print(f"No photos found in {args.pictures}")
        return
    print(f"{sum(len(v) for v in sessions.values())} photos in {len(sessions)} walk(s) in {args.pictures}\n")
    for name, frames in sessions.items():
        local = LocalFrame(frames[0].latitude, frames[0].longitude)
        xy = np.array([local.to_local(f.latitude, f.longitude) for f in frames])
        spread = np.ptp(xy, axis=0) if len(xy) else np.zeros(2)
        seconds = frames[-1].taken_at - frames[0].taken_at
        accuracy = np.median([f.gps_accuracy_m for f in frames])
        described = sum(f.has_description for f in frames)
        print(f"{name}")
        print(f"  photos: {len(frames)} ({described} with a description file), time span: {seconds:.0f} s")
        print(f"  GPS spread: {spread[0]:.1f} m east-west, {spread[1]:.1f} m north-south, median accuracy {accuracy:.0f} m")
        if described < len(frames):
            print("  note: photos without a description file have no tilt or accuracy, so results will be rougher")


# --------------------------------------------------------------------------------- calibrate-scale

def command_calibrate_scale(args) -> None:
    """Tell it that the thing at pixel (x, y) is really N metres away; it works out the correction."""
    from PIL import Image

    settings = _settings_from(args)
    try:
        from .models import DepthEstimator
    except ImportError as error:
        raise SystemExit(f"The AI libraries are not installed ({error}).\nRun:  pip install -r requirements-models.txt")
    estimator = DepthEstimator(settings.depth_model, settings.device)
    image = Image.open(args.image).convert("RGB")
    depth = estimator.predict(image)
    x, y = args.x, args.y
    window = depth[max(0, y - 4): y + 5, max(0, x - 4): x + 5]
    measured = float(np.median(window))
    factor = args.distance / measured
    print(f"The model says {measured:.2f} m at ({x}, {y}); you measured {args.distance:.2f} m.")
    print(f"Correction factor: {factor:.3f}")
    previous = {}
    if CALIBRATION_FILE.exists():
        previous = json.loads(CALIBRATION_FILE.read_text(encoding="utf-8"))
    previous["depth_scale"] = round(factor, 4)
    CALIBRATION_FILE.write_text(json.dumps(previous, indent=2), encoding="utf-8")
    print(f"Saved to {CALIBRATION_FILE}; `build` uses it automatically. Repeat in a few rooms and average if they differ.")


# ----------------------------------------------------------------------------------------------- demo

def command_demo(args) -> None:
    """A made-up 6 x 4 m room: checks the whole pipeline (apart from the neural networks) works."""
    from datetime import datetime, timezone

    from .geo import LocalFrame
    from .pipeline import build
    from .synthetic import FakeDepth, FakeSegmenter, Room, walk_room

    room = Room(width=6.0, depth=4.0)
    local = LocalFrame(53.5260874, -113.5203733)
    loop = [(1.0, 1.0), (5.0, 1.0), (5.0, 3.0), (1.0, 3.0), (1.0, 1.0)]
    print("Making pretend photos with a noisy GPS (4 m) and a wobbly compass (8 degrees) ...")
    frames, truth, _ = walk_room(room, local, loop, step_m=0.6, gps_noise_m=4.0, compass_noise_deg=8.0)

    # Put the pretend photos into a throwaway Pictures folder so the real loader reads them like real ones.
    import shutil
    import tempfile
    folder = Path(tempfile.mkdtemp(prefix="floorplan-demo-"))
    session = folder / "demo-walk"
    session.mkdir(parents=True)
    for frame in frames:
        shutil.copy(frame.path, session / frame.path.name)
        (session / frame.path.with_suffix(".json").name).write_text(json.dumps({
            "version": 1, "session": "demo-walk", "seq": frame.seq,
            "takenAt": datetime.fromtimestamp(frame.taken_at, timezone.utc).isoformat(),
            "latitude": frame.latitude, "longitude": frame.longitude, "gpsAccuracyM": frame.gps_accuracy_m,
            "headingDeg": frame.heading_deg, "pitchDeg": frame.pitch_deg, "rollDeg": frame.roll_deg,
            "assumedFovLongSideDeg": frame.fov_long_side_deg,
        }), encoding="utf-8")

    settings = _settings_from(args)
    settings.pose_smoothing_window = 3
    result = build(folder, Path(args.out) / "demo", settings, FakeDepth(truth), FakeSegmenter(truth))

    # How close did we get to the true 6 x 4 m rectangle?
    xs = [v for w in result.walls for v in (w.x0, w.x1)]
    ys = [v for w in result.walls for v in (w.y0, w.y1)]
    if xs:
        print(f"\nDetected walls span {max(xs) - min(xs):.2f} m x {max(ys) - min(ys):.2f} m (true room: 6.00 x 4.00)")
    print(f"Open {Path(args.out) / 'demo' / 'floorplan.png'}")
    shutil.rmtree(folder, ignore_errors=True)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="python -m floorplan", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    build_parser = sub.add_parser("build", help="make a floor plan from the photos")
    build_parser.add_argument("--pictures", default=str(DEFAULT_PICTURES), help="folder the navigator saves photos in")
    build_parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="where to write the results")
    build_parser.add_argument("--session", help="only use this walk (a folder name inside Pictures)")
    build_parser.add_argument("--no-refine", action="store_true", help="use raw GPS and compass, skip the visual correction")
    build_parser.add_argument("--manhattan", action="store_true", help="snap walls to the building's main directions")
    _add_settings_options(build_parser)
    build_parser.set_defaults(handler=command_build)

    inspect_parser = sub.add_parser("inspect", help="summarise the collected photos (no AI needed)")
    inspect_parser.add_argument("--pictures", default=str(DEFAULT_PICTURES))
    inspect_parser.set_defaults(handler=command_inspect)

    scale_parser = sub.add_parser("calibrate-scale", help="correct the depth model with a tape-measure distance")
    scale_parser.add_argument("--image", required=True)
    scale_parser.add_argument("--x", type=int, required=True, help="pixel column of the thing you measured")
    scale_parser.add_argument("--y", type=int, required=True, help="pixel row of the thing you measured")
    scale_parser.add_argument("--distance", type=float, required=True, help="real distance in metres (straight out from the camera)")
    _add_settings_options(scale_parser)
    scale_parser.set_defaults(handler=command_calibrate_scale)

    demo_parser = sub.add_parser("demo", help="run on a made-up room (no AI or photos needed)")
    demo_parser.add_argument("--out", default=str(DEFAULT_OUTPUT))
    demo_parser.add_argument("--no-refine", action="store_true")
    demo_parser.add_argument("--manhattan", action="store_true")
    _add_settings_options(demo_parser)
    demo_parser.set_defaults(handler=command_demo)

    args = parser.parse_args(argv)
    args.handler(args)


if __name__ == "__main__":
    main()
