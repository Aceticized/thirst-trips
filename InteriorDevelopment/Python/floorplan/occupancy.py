"""A top-down grid that remembers, for every square of floor, whether it is wall, free, or unknown.

Each cell stores "log odds" of being occupied. Every scan pushes the cells along each ray from the camera to a
wall point towards "free", and the wall point's own cell towards "occupied". A cell is changed at most once per
photo, so one photo cannot outvote the rest by sending many rays through the same cell.
"""

import math

import numpy as np

from .config import Settings
from .scan import Scan


class OccupancyGrid:
    def __init__(self, x_min: float, y_min: float, nx: int, ny: int, cell: float, settings: Settings):
        self.x_min, self.y_min, self.nx, self.ny, self.cell = x_min, y_min, nx, ny, cell
        self.settings = settings
        self.log_odds = np.zeros((ny, nx), dtype=np.float32)   # row 0 is the south edge

    @classmethod
    def covering(cls, scans: list[Scan], settings: Settings) -> "OccupancyGrid":
        points = [np.vstack([s.camera_xy[None, :], s.hits_xy, s.floor_xy]) for s in scans if not s.empty]
        if not points:
            points = [np.zeros((1, 2))]
        everything = np.vstack(points)
        low = everything.min(axis=0) - settings.padding_m
        high = everything.max(axis=0) + settings.padding_m
        nx = int(math.ceil((high[0] - low[0]) / settings.cell_size_m)) + 1
        ny = int(math.ceil((high[1] - low[1]) / settings.cell_size_m)) + 1
        return cls(float(low[0]), float(low[1]), nx, ny, settings.cell_size_m, settings)

    # ----- coordinates -----

    def _index(self, xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        ix = np.floor((xy[:, 0] - self.x_min) / self.cell).astype(np.int64)
        iy = np.floor((xy[:, 1] - self.y_min) / self.cell).astype(np.int64)
        return ix, iy

    def _linear(self, xy: np.ndarray) -> np.ndarray:
        ix, iy = self._index(xy)
        inside = (ix >= 0) & (ix < self.nx) & (iy >= 0) & (iy < self.ny)
        return iy[inside] * self.nx + ix[inside]

    def cell_centre(self, ix: float, iy: float) -> tuple[float, float]:
        return self.x_min + (ix + 0.5) * self.cell, self.y_min + (iy + 0.5) * self.cell

    @property
    def extent(self) -> tuple[float, float, float, float]:
        """x_min, x_max, y_min, y_max in metres."""
        return self.x_min, self.x_min + self.nx * self.cell, self.y_min, self.y_min + self.ny * self.cell

    # ----- adding evidence -----

    def add_scan(self, scan: Scan) -> None:
        s = self.settings
        flat = self.log_odds.reshape(-1)

        hit_cells = np.unique(self._linear(scan.hits_xy)) if len(scan.hits_xy) else np.zeros(0, dtype=np.int64)

        free_cells = np.zeros(0, dtype=np.int64)
        if len(scan.hits_xy):
            vectors = scan.hits_xy - scan.camera_xy
            distances = np.hypot(vectors[:, 0], vectors[:, 1])
            step = self.cell * 0.5
            n_steps = int(np.ceil(distances.max() / step)) + 1
            fractions = (np.arange(n_steps)[None, :] * step) / np.maximum(distances[:, None], 1e-6)
            keep = (fractions * distances[:, None]) < (distances[:, None] - self.cell)   # stop before the wall
            along = scan.camera_xy[None, None, :] + fractions[..., None] * vectors[:, None, :]
            free_cells = np.unique(self._linear(along[keep]))

        floor_cells = np.unique(self._linear(scan.floor_xy)) if len(scan.floor_xy) else np.zeros(0, dtype=np.int64)

        free_cells = np.setdiff1d(free_cells, hit_cells)
        floor_cells = np.setdiff1d(floor_cells, np.concatenate([hit_cells, free_cells]))
        flat[free_cells] -= s.log_odds_free
        flat[floor_cells] -= s.log_odds_floor
        flat[hit_cells] += s.log_odds_occupied
        np.clip(self.log_odds, s.log_odds_min, s.log_odds_max, out=self.log_odds)

    # ----- reading it back -----

    def occupied(self) -> np.ndarray:
        return self.log_odds > self.settings.occupied_threshold

    def free(self) -> np.ndarray:
        return self.log_odds < self.settings.free_threshold

    def observed(self) -> np.ndarray:
        return np.abs(self.log_odds) > 1e-6
