import sys
from pathlib import Path

# Lets the tests import the floorplan package when run from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent))
