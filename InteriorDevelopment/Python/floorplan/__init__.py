"""Turns the snapshots collected by the navigator into a top-down floor plan.

Stages (each one is its own module):

    dataset            reads InteriorDevelopment/Pictures (photos plus their .json description)
    models             metric depth (Depth Anything V2) and wall/floor labels (Mask2Former, ADE20K)
    camera, scan       photo + depth + labels  ->  where the walls are around the camera
    visual_odometry,
    poses              better camera positions and headings than raw GPS and compass
    occupancy, walls   many scans -> a 2D grid -> straight wall lines
    render, pipeline   pictures, SVG, JSON, and the glue that runs everything
"""

__version__ = "0.1.0"
