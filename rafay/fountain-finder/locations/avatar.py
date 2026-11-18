"""The raccoon avatar: which accessories exist, what they cost in points, and what a player is wearing.

Every accessory is a transparent layer the same size as the base raccoon (see scripts/build_art_assets.py), so an
avatar is just the base picture with the worn layers stacked on top. To add an accessory, drop its picture in
emily/, add it to LAYERS in that script, run the script, and add one line to ITEMS below.

An accessory unlocks for good once the player's total points reach its `points`. Eyes and mouth are one choice
each; so is the top; the hat is separate. Taking an item off (an empty choice) is always allowed.
"""

from dataclasses import dataclass

from django.templatetags.static import static

# The part of emily's original 2126 x 2538 pictures that the avatar pictures show (left, top, right, bottom).
# Must match CROP in scripts/build_art_assets.py.
AVATAR_CROP = (215, 414, 1994, 1745)
ASSET_VERSION = "1"          # change when the pictures change, so phones fetch the new ones

# Drawn on top of the base in this order (later ones cover earlier ones).
SLOTS = ("top", "eyes", "mouth", "hat")

# Shown when a player has not chosen anything yet.
DEFAULTS = {"top": "", "eyes": "white", "mouth": "happy", "hat": ""}

# A square window onto the original picture: (centre x, centre y, side). Used to zoom in on an accessory.
BUST = (785, 980, 1100)       # head and shoulders, for the leaderboard
FOCUS = {
    "top": (750, 1400, 700),
    "eyes": (750, 1190, 700),
    "mouth": (790, 1255, 420),
    "hat": (1144, 800, 520),
}


@dataclass(frozen=True)
class Item:
    slot: str
    key: str
    name: str
    points: int = 0          # total points needed to unlock

    @property
    def file(self) -> str:
        return f"locations/avatar/{self.slot}-{self.key}.png"

    @property
    def focus(self):
        return FOCUS[self.slot]


ITEMS = (
    Item("eyes", "white", "Default eyes", 0),
    Item("eyes", "square", "Square eyes", 0),
    Item("eyes", "side", "Side eyes", 40),
    Item("eyes", "sad", "Sad eyes", 60),
    Item("eyes", "wise", "Wise eyes", 150),
    Item("mouth", "happy", "Happy smile", 0),
    Item("mouth", "sad", "Sad mouth", 0),
    Item("mouth", "coy", "Coy smile", 30),
    Item("mouth", "tongue", "Tongue out", 80),
    Item("top", "h2o", "H2O tank top", 0),
    Item("top", "pizza", "Pizza tee", 100),
    Item("top", "drippy", "Drippy tee", 200),
    Item("hat", "bow", "Bow", 25),
)

# The three tabs of the wardrobe: (id, title, picture, [(slot, heading), ...])
TABS = (
    ("clothing", "Clothes", "locations/avatar/tab-clothing.png", (("top", "Tops"), ("hat", "Accessories"))),
    ("eyes", "Eyes", "locations/avatar/tab-eyes.png", (("eyes", "Eyes"),)),
    ("mouth", "Mouth", "locations/avatar/tab-mouth.png", (("mouth", "Mouth"),)),
)

_BY_SLOT = {slot: {item.key: item for item in ITEMS if item.slot == slot} for slot in SLOTS}


def find_item(slot: str, key: str):
    return _BY_SLOT.get(slot, {}).get(key)


def is_unlocked(item: Item, points: int) -> bool:
    return points >= item.points


def asset_url(path: str) -> str:
    return f"{static(path)}?v={ASSET_VERSION}"


def equipped_for(profile) -> dict:
    """What the player is wearing. Anything unknown or not (or no longer) unlocked is left off."""
    stored = {
        "top": profile.avatar_top, "eyes": profile.avatar_eyes,
        "mouth": profile.avatar_mouth, "hat": profile.avatar_hat,
    }
    worn = {}
    for slot in SLOTS:
        item = find_item(slot, stored[slot])
        worn[slot] = item.key if item and is_unlocked(item, profile.total_points) else ""
    return worn


def clean_choices(posted: dict, points: int):
    """Checks what the player picked. Returns (choices, error); error is None when everything is allowed.

    Only slots that appear in `posted` are returned. An empty value takes that item off.
    """
    choices = {}
    for slot in SLOTS:
        if slot not in posted:
            continue
        key = posted[slot]
        if key == "":
            choices[slot] = ""
            continue
        item = find_item(slot, key)
        if item is None:
            return {}, "That item doesn't exist."
        if not is_unlocked(item, points):
            return {}, f"{item.name} unlocks at {item.points} points."
        choices[slot] = key
    return choices, None


def save_choices(profile, choices: dict) -> None:
    fields = []
    for slot, key in choices.items():
        field = f"avatar_{slot}"
        setattr(profile, field, key)
        fields.append(field)
    if fields:
        profile.save(update_fields=fields)


def wardrobe(points: int, equipped: dict) -> list:
    """Everything the customization screen needs, grouped by tab."""
    tabs = []
    for tab_id, title, icon, groups in TABS:
        built = []
        for slot, heading in groups:
            items = []
            for item in ITEMS:
                if item.slot != slot:
                    continue
                items.append({
                    "item": item, "slot": slot, "key": item.key, "name": item.name, "points": item.points,
                    "unlocked": is_unlocked(item, points), "worn": equipped.get(slot) == item.key,
                })
            built.append({"slot": slot, "heading": heading, "items": items})
        tabs.append({"id": tab_id, "title": title, "icon": asset_url(icon), "groups": built})
    return tabs


def next_unlock(points: int):
    """The cheapest item the player doesn't have yet, or None when everything is unlocked."""
    locked = [item for item in ITEMS if not is_unlocked(item, points)]
    return min(locked, key=lambda item: item.points) if locked else None


def view_styles(focus=None):
    """CSS for showing the whole avatar (focus=None) or a square zoomed in on `focus` = (x, y, side)."""
    width = AVATAR_CROP[2] - AVATAR_CROP[0]
    height = AVATAR_CROP[3] - AVATAR_CROP[1]
    if focus is None:
        return f"aspect-ratio:{width}/{height}", "left:0;top:0;width:100%"
    cx, cy, side = focus
    left = -(cx - side / 2 - AVATAR_CROP[0]) / side * 100
    top = -(cy - side / 2 - AVATAR_CROP[1]) / side * 100
    return "aspect-ratio:1/1", f"left:{left:.3f}%;top:{top:.3f}%;width:{width / side * 100:.3f}%"
