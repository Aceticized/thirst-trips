"""Pictures, SVG and JSON of the result."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from .occupancy import OccupancyGrid  # noqa: E402
from .walls import Segment  # noqa: E402


def occupancy_image(grid: OccupancyGrid) -> np.ndarray:
    """RGB image, row 0 = south: unknown grey, free white, wall near-black."""
    image = np.full((grid.ny, grid.nx, 3), 0.82, dtype=np.float32)
    image[grid.free()] = (1.0, 1.0, 1.0)
    image[grid.occupied()] = (0.12, 0.12, 0.14)
    return image


def save_debug_picture(grid: OccupancyGrid, walls: list[Segment], path_xy: np.ndarray, out_file: Path) -> None:
    """The occupancy grid with the walked path and the detected walls on top. Useful for checking the result."""
    x0, x1, y0, y1 = grid.extent
    fig, ax = plt.subplots(figsize=(9, 9 * (y1 - y0) / max(x1 - x0, 1e-6) if x1 > x0 else 9))
    ax.imshow(occupancy_image(grid), origin="lower", extent=(x0, x1, y0, y1), interpolation="nearest")
    if len(path_xy):
        ax.plot(path_xy[:, 0], path_xy[:, 1], "-", color="#2e9e4f", linewidth=1.5, label="camera path")
        ax.plot(path_xy[0, 0], path_xy[0, 1], "o", color="#2e9e4f")
    for i, w in enumerate(walls):
        ax.plot([w.x0, w.x1], [w.y0, w.y1], "-", color="#d62728", linewidth=2, label="walls" if i == 0 else None)
    ax.set_xlabel("metres east")
    ax.set_ylabel("metres north")
    ax.set_aspect("equal")
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(out_file, dpi=140)
    plt.close(fig)


def save_clean_plan(grid: OccupancyGrid, walls: list[Segment], out_file: Path) -> None:
    """Just the walls, like a drawn floor plan, with a scale bar and a north arrow."""
    x0, x1, y0, y1 = grid.extent
    fig, ax = plt.subplots(figsize=(9, 9 * (y1 - y0) / max(x1 - x0, 1e-6) if x1 > x0 else 9))
    for w in walls:
        ax.plot([w.x0, w.x1], [w.y0, w.y1], "-", color="black", linewidth=4, solid_capstyle="round")
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")
    ax.axis("off")
    bar_x, bar_y = x0 + 0.05 * (x1 - x0), y0 + 0.04 * (y1 - y0)
    ax.plot([bar_x, bar_x + 2.0], [bar_y, bar_y], "-", color="black", linewidth=3)
    ax.text(bar_x + 1.0, bar_y + 0.15, "2 m", ha="center", fontsize=9)
    arrow_x, arrow_y = x1 - 0.06 * (x1 - x0), y1 - 0.14 * (y1 - y0)
    ax.annotate("N", xy=(arrow_x, arrow_y + 0.9), xytext=(arrow_x, arrow_y), ha="center", fontsize=11,
                arrowprops=dict(arrowstyle="-|>", color="black"))
    fig.tight_layout()
    fig.savefig(out_file, dpi=140, facecolor="white")
    plt.close(fig)


def save_svg(grid: OccupancyGrid, walls: list[Segment], out_file: Path) -> None:
    """Walls as lines in metres (1 unit = 1 m). North is up."""
    x0, x1, y0, y1 = grid.extent
    lines = "\n".join(
        f'  <line x1="{w.x0 - x0:.3f}" y1="{y1 - w.y0:.3f}" x2="{w.x1 - x0:.3f}" y2="{y1 - w.y1:.3f}"/>' for w in walls
    )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {x1 - x0:.3f} {y1 - y0:.3f}" '
        f'width="{(x1 - x0) * 50:.0f}" height="{(y1 - y0) * 50:.0f}">\n'
        f'<g stroke="black" stroke-width="0.12" stroke-linecap="round" fill="none">\n{lines}\n</g>\n</svg>\n'
    )
    out_file.write_text(svg, encoding="utf-8")


def save_json(grid: OccupancyGrid, walls: list[Segment], origin: tuple[float, float], extra: dict, out_file: Path) -> None:
    x0, x1, y0, y1 = grid.extent
    payload = {
        "units": "metres",
        "axes": "x = east, y = north, relative to origin",
        "origin_latitude": origin[0],
        "origin_longitude": origin[1],
        "extent": {"x_min": x0, "x_max": x1, "y_min": y0, "y_max": y1},
        "cell_size_m": grid.cell,
        "walls": [w.to_list() for w in walls],
        **extra,
    }
    out_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
