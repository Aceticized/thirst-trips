"""Makes the web-sized pictures from the artwork in the emily folder: the raccoon avatar and the achievement popups.

Avatar: every layer in emily/ is the same 2126 x 2538 transparent picture, with the accessory already in the right
place on the raccoon. Here each one is cropped to the same box around the raccoon and shrunk to the same size, so
they still line up when stacked. They go to locations/static/locations/avatar/.

Achievements: each badge is cropped to the same box and shrunk, and saved as <achievement code>.png in
locations/static/locations/achievements/, where the popup looks for it.

The results are committed. Run this again whenever the artwork changes (needs Pillow):

    python scripts/build_art_assets.py

If you change CROP or WIDTH, change AVATAR_CROP in locations/avatar.py to match.
"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT.parent.parent / "emily"
STATIC = ROOT / "locations" / "static" / "locations"
OUT = STATIC / "avatar"
ACHIEVEMENT_OUT = STATIC / "achievements"

CROP = (215, 414, 1994, 1745)   # left, top, right, bottom in the original picture: the raccoon plus a little margin
WIDTH = 800                     # width of every avatar layer after shrinking
ICON_HEIGHT = 160

# The four badges share one layout, so one box fits all (this also leaves out a stray speck in one of them).
ACHIEVEMENT_CROP = (470, 385, 1895, 1165)
ACHIEVEMENT_WIDTH = 900

# output name -> source file in emily/
LAYERS = {
    "base": "characterbase",
    "eyes-white": "default white eyes",
    "eyes-sad": "sad eyes",
    "eyes-side": "side eyes",
    "eyes-square": "square eyes",
    "eyes-wise": "wise eyes",
    "mouth-happy": "happy mouth (default)",
    "mouth-sad": "sad mouth",
    "mouth-coy": "coy smile",
    "mouth-tongue": "all tongue",
    "top-h2o": "H2O tank top",
    "top-pizza": "pizza tee",
    "top-drippy": "drippy tee",
    "hat-bow": "girl bow",
}

ICONS = {
    "tab-clothing": "clothing icon(wardrobe)",
    "tab-eyes": "eye icon (wardrobe)",
    "tab-mouth": "mouth icon (wardrobe)",
    "edit-avatar": "edit avatar icon",
}

# achievement code (see locations/achievements.py) -> source file in emily/
ACHIEVEMENTS = {
    "new_fountain": "Fountain Finder Achievement",
    "first_check_in": "First Sip Achievement",
    "points_50": "Getting Hydrated Achievement",
    "fountains_5": "Fountain Explorer Achievement",
}


def tight_box(image: Image.Image, pad: int = 4):
    """Bounding box of the solid pixels, plus a little padding (ignores faint stray specks in the artwork)."""
    left, top, right, bottom = image.getchannel("A").point(lambda a: 255 if a > 200 else 0).getbbox()
    return (max(left - pad, 0), max(top - pad, 0), min(right + pad, image.width), min(bottom + pad, image.height))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ACHIEVEMENT_OUT.mkdir(parents=True, exist_ok=True)

    height = round(WIDTH * (CROP[3] - CROP[1]) / (CROP[2] - CROP[0]))
    for name, source in LAYERS.items():
        image = Image.open(ART / f"{source}.png").convert("RGBA")
        layer = image.crop(CROP).resize((WIDTH, height), Image.LANCZOS)
        layer.save(OUT / f"{name}.png", optimize=True)

    for name, source in ICONS.items():
        image = Image.open(ART / f"{source}.png").convert("RGBA")
        icon = image.crop(tight_box(image))
        icon = icon.resize((round(icon.width * ICON_HEIGHT / icon.height), ICON_HEIGHT), Image.LANCZOS)
        icon.save(OUT / f"{name}.png", optimize=True)

    badge_height = round(ACHIEVEMENT_WIDTH * (ACHIEVEMENT_CROP[3] - ACHIEVEMENT_CROP[1]) / (ACHIEVEMENT_CROP[2] - ACHIEVEMENT_CROP[0]))
    for code, source in ACHIEVEMENTS.items():
        image = Image.open(ART / f"{source}.png").convert("RGBA")
        badge = image.crop(ACHIEVEMENT_CROP).resize((ACHIEVEMENT_WIDTH, badge_height), Image.LANCZOS)
        badge.save(ACHIEVEMENT_OUT / f"{code}.png", optimize=True)

    avatar_kb = sum(f.stat().st_size for f in OUT.glob("*.png")) // 1024
    badge_kb = sum((ACHIEVEMENT_OUT / f"{c}.png").stat().st_size for c in ACHIEVEMENTS) // 1024
    print(f"wrote {len(LAYERS)} avatar layers ({WIDTH}x{height}) and {len(ICONS)} icons ({avatar_kb} KB), "
          f"{len(ACHIEVEMENTS)} achievement badges ({ACHIEVEMENT_WIDTH}x{badge_height}, {badge_kb} KB)")


if __name__ == "__main__":
    main()
