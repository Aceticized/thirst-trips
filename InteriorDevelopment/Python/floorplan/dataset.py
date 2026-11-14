"""Reads the photos saved by the navigator.

New style (one folder per walk):
    Pictures/<session>/0007 53.1023982 -113.2034985 349.jpg   plus   ... 349.json with the details
Old style (everything in Pictures itself, no description file):
    Pictures/53.1023982 -113.2034985 349.jpg
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

IMAGE_SUFFIXES = {".jpg", ".jpeg"}

NEW_NAME = re.compile(r"^(?P<seq>\d+) (?P<lat>-?\d+\.\d+) (?P<lon>-?\d+\.\d+) (?P<heading>\d{1,3})(?: \(\d+\))?$")
OLD_NAME = re.compile(r"^(?P<lat>-?\d+\.\d+) (?P<lon>-?\d+\.\d+) (?P<heading>\d{1,3})(?: \(\d+\))?$")

DEFAULT_FOV_LONG_SIDE_DEG = 70.0   # what the navigator assumes
DEFAULT_GPS_ACCURACY_M = 20.0      # for old-style photos that did not record it


@dataclass
class Frame:
    path: Path
    session: str
    seq: int
    taken_at: float          # seconds since 1970
    latitude: float
    longitude: float
    gps_accuracy_m: float
    heading_deg: float       # direction the camera faces, clockwise from true north
    pitch_deg: float         # positive looks up
    roll_deg: float          # positive when the right side of the picture is higher
    fov_long_side_deg: float
    has_description: bool    # False: only the file name was available

    @property
    def stem(self) -> str:
        return self.path.stem


def _from_description(path: Path, session: str, data: dict) -> Frame:
    from datetime import datetime

    taken = data.get("takenAt")
    try:
        taken_at = datetime.fromisoformat(taken.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        taken_at = path.stat().st_mtime
    return Frame(
        path=path,
        session=data.get("session", session),
        seq=int(data.get("seq", 0)),
        taken_at=taken_at,
        latitude=float(data["latitude"]),
        longitude=float(data["longitude"]),
        gps_accuracy_m=float(data.get("gpsAccuracyM", DEFAULT_GPS_ACCURACY_M)),
        heading_deg=float(data["headingDeg"]) % 360.0,
        pitch_deg=float(data.get("pitchDeg", 0.0)),
        roll_deg=float(data.get("rollDeg", 0.0)),
        fov_long_side_deg=float(data.get("assumedFovLongSideDeg", DEFAULT_FOV_LONG_SIDE_DEG)),
        has_description=True,
    )


def _from_name(path: Path, session: str, index: int) -> Frame | None:
    match = NEW_NAME.match(path.stem)
    seq = int(match["seq"]) if match else index
    match = match or OLD_NAME.match(path.stem)
    if not match:
        return None
    return Frame(
        path=path,
        session=session,
        seq=seq,
        taken_at=path.stat().st_mtime,
        latitude=float(match["lat"]),
        longitude=float(match["lon"]),
        gps_accuracy_m=DEFAULT_GPS_ACCURACY_M,
        heading_deg=float(match["heading"]) % 360.0,
        pitch_deg=0.0,
        roll_deg=0.0,
        fov_long_side_deg=DEFAULT_FOV_LONG_SIDE_DEG,
        has_description=False,
    )


def load_frames(pictures_dir: Path) -> dict[str, list[Frame]]:
    """Every readable photo, grouped by walk and put in the order it was taken."""
    pictures_dir = Path(pictures_dir)
    sessions: dict[str, list[Frame]] = {}
    images = sorted(p for p in pictures_dir.rglob("*") if p.suffix.lower() in IMAGE_SUFFIXES)
    for index, image in enumerate(images):
        session = image.parent.name if image.parent != pictures_dir else "loose-photos"
        frame = None
        description = image.with_suffix(".json")
        if description.exists():
            try:
                frame = _from_description(image, session, json.loads(description.read_text(encoding="utf-8")))
            except (OSError, ValueError, KeyError, TypeError):
                frame = None
        if frame is None:
            frame = _from_name(image, session, index)
        if frame is not None:
            sessions.setdefault(frame.session, []).append(frame)
    for frames in sessions.values():
        frames.sort(key=lambda f: (f.taken_at, f.seq))
    return sessions
