# Interior floor plans from the navigator's photos

This turns the photos the navigator collects (`InteriorDevelopment/Pictures`) into a top-down floor plan:
wall lines, the walkable floor, and the path the camera took.

```
photo + its .json  ->  depth (metres)  ->  where are the walls around the camera?  ->  grid  ->  wall lines
                  \->  labels (wall, floor, door ...) ->/                              ^
 GPS + compass  ->  corrected by comparing consecutive photos  ----------------------/
```

## Try it in one minute (no downloads, no AI)

```powershell
cd InteriorDevelopment\Python
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m floorplan demo
```

`demo` walks a pretend camera around a made-up 6 x 4 m room with a bad GPS (4 m) and a wobbly compass, runs the
real pipeline on it, and writes `output/demo/floorplan.png`. It is also how the code is tested.

## Using it on the real photos

```powershell
.\.venv\Scripts\python.exe -m floorplan inspect          # what has been collected so far (no AI needed)
.\.venv\Scripts\python.exe -m floorplan build            # make the plan (needs the AI models, see below)
```

Results go to `output/` (ignored by Git):

| File | What it is |
|---|---|
| `floorplan.png` | Clean plan: just the walls, a scale bar and a north arrow. |
| `floorplan_debug.png` | The grid (grey unknown, white free floor, dark walls) with the walked path and detected walls drawn on top. Look at this first when something seems off. |
| `floorplan.svg` | The walls as lines, 1 unit = 1 metre, north up. |
| `floorplan.json` | The same walls as numbers: metres east/north of an origin whose latitude/longitude is stored in the file. |
| `poses.csv` | Where the program thinks each photo was taken from, and which way it faced. |
| `occupancy_log_odds.npy` | The raw grid (a NumPy array) if you want to do something else with it. |
| `cache/` | Depth and labels per photo, so running again is fast. Delete it to recompute. |

Useful options: `--session <folder name>` to use one walk, `--manhattan` to snap walls to the building's main
directions, `--no-refine` to skip the visual correction, `--cell 0.05` for a finer grid, `--stride 4` for more
detail per photo (slower), `--device cpu|cuda`.

### The AI models

`build` uses two models from Hugging Face, downloaded the first time (about 1.3 GB and 0.9 GB):

- **Depth Anything V2, metric indoor** (`depth-anything/Depth-Anything-V2-Metric-Indoor-Large-hf`): distance in metres per pixel.
- **Mask2Former on ADE20K** (`facebook/mask2former-swin-large-ade-semantic`): wall / floor / ceiling / door / window / person per pixel.

```powershell
py install 3.12                                      # once; installs Python 3.12 next to your other Python
py -3.12 -m venv .venv-models
.\.venv-models\Scripts\python.exe -m pip install -r requirements-models.txt
.\.venv-models\Scripts\python.exe -m floorplan build
```
On a laptop CPU expect roughly 10 to 30 seconds per photo with the large models. Smaller ones are faster and less
accurate: `--depth-model depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf --segmentation-model facebook/mask2former-swin-tiny-ade-semantic`.

> **Python version.** `requirements.txt` installs fine on any recent Python, including 3.15. The AI packages
> need PyYAML, which has no ready-made package for the newest Python versions and then wants the Microsoft C++
> Build Tools. Use Python **3.12 or 3.13** (https://python.org, side by side with your other Python) for
> `requirements-models.txt`.

> **Tested with the real models** on a 19-photo walk (CPU, Python 3.12): both models download and run, and the
> result is a recognisable room. Expect the first run to take a few minutes just to download and load them.
### Calibrate the depth scale (do this once, it matters)

A single photo cannot know its absolute scale, so metric depth models can be 10 to 20% off in a given building.
Measure with a tape: stand at a flat wall, take a photo straight on, and note the real distance and the pixel you
measured to:

```powershell
.\.venv-models\Scripts\python.exe -m floorplan calibrate-scale --image "Pictures\<walk>\0003 ... .jpg" --x 640 --y 360 --distance 3.2
```

It saves a correction factor in `calibration.json`, which `build` then uses. Repeat in a few rooms; if the factors
differ a lot, use the average.

## What is in each photo's description file

The navigator saves `0007 53.1023982 -113.2034985 349.jpg` plus `0007 53.1023982 -113.2034985 349.json`
inside a folder named after the walk (`20261114-031542-k3x9`). The file name keeps the three numbers visible
(latitude, longitude, compass angle); the `.json` has everything else:

| Field | Meaning |
|---|---|
| `takenAt` | UTC time |
| `latitude`, `longitude`, `gpsAccuracyM` | GPS and how much it says it can be off |
| `headingDeg` | Direction the camera faces, degrees clockwise from **true** north (declination already applied) |
| `pitchDeg` | Camera tilt: positive looks up, negative looks down |
| `rollDeg` | Positive when the right side of the picture is higher |
| `magneticDeclinationDeg`, `manualCompassOffsetDeg` | How the heading was corrected (for reference) |
| `imageWidth`, `imageHeight` | Size of the saved picture |
| `assumedFovLongSideDeg` | A **guess** (70) of the camera's field of view along its long side, not measured per phone |

Photos in the old style (`53.1023982 -113.2034985 349.jpg` straight in `Pictures`, no description) still load, with
no tilt or GPS accuracy, so the result will be rougher.

## How it works, step by step

1. **Depth and labels** (`models.py`): both networks run on each photo; the results are cached.
2. **A scan per photo** (`scan.py`): pixels become 3D points using depth, the camera's field of view, and its
   direction. For every picture column, the nearest wall pixel (door and window pixels count as wall) becomes a
   "laser" hit. People are ignored, and so are wall pixels that are too close to the floor or too high.
3. **Better camera poses** (`visual_odometry.py`, `poses.py`): GPS and compass are only a starting point.
   Features are matched between consecutive photos; the first photo's depth turns them into 3D points, and PnP
   gives the camera's real movement in metres. A small least-squares fit then combines it all: the visual
   turns are trusted tightly, the compass loosely, and GPS only decides where the whole walk sits on the map. A
   visual match that disagrees with the rest fades out. If neighbouring photos cannot be matched (a sharp turn),
   the next few photos are tried, and a weak "a person cannot jump across the room" link keeps the halves together.
4. **The grid** (`occupancy.py`): every scan marks the cells between the camera and each wall hit as free, and the
   hit cell as occupied (evidence adds up over photos).
5. **Walls** (`walls.py`): occupied cells become straight lines (Hough transform), nearly collinear pieces are
   merged, and with `--manhattan` they are snapped square to the building's main directions.

## How accurate is it?

Measured on the pretend room (`tests/test_floorplan.py` checks these):

- With perfect camera poses the 6 x 4 m room comes back to within 0.3 m.
- With a GPS that is 1 m off and a compass 4 degrees off, the visual correction brings the plan to about 7.4 x 4.4 m;
  raw GPS and compass give about 9.7 x 5.4 m. With a GPS 6 m off, the corrected plan is still about 7.4 x 4.5 m,
  because GPS only places the whole walk, not each photo.
- The remaining error is mostly sections of a walk sitting about half a metre apart, which shows up as doubled walls.

Real buildings are harder than the pretend room: glass, mirrors and blank walls confuse depth and matching, and the
phone's field of view is a guess. Expect something useful for room layout, not survey accuracy.

## Where to go next

- **Loop closure**: when the walk returns to a place it has already seen, tie those photos together (this is what
  removes the doubled walls).
- **Stronger pose estimation**: COLMAP or MASt3R/VGGT in place of `visual_odometry.py`. `refine_poses` only needs
  "camera i moved to camera j by this rotation and translation (metres)", so swapping the source is local.
- **Floor-plan models** such as RoomFormer on the occupancy picture, instead of Hough lines.
- **Door and window openings** from the labels (currently they count as wall).
- **A measured field of view** per phone model (`--fov`), which improves everything.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

They build a pretend building (`synthetic.py`) that renders textured photos with exact depth and labels, so the
geometry, the camera correction, the grid, the walls, the folder reader and the command line are all checked
without any AI model.
