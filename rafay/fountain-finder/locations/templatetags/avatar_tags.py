from django import template

from .. import avatar as av

register = template.Library()


def _picture(layers, focus, label="", css_class="", preview=False):
    box_style, stage_style = av.view_styles(focus)
    return {
        "layers": layers, "box_style": box_style, "stage_style": stage_style,
        "label": label, "css_class": css_class, "preview": preview,
    }


@register.inclusion_tag("locations/_avatar.html")
def avatar(equipped, view="full", label="", css_class="", preview=False):
    """A player's raccoon. view is "full" (the whole raccoon) or "bust" (head and shoulders).

    With preview=True every slot gets a picture element, empty ones hidden, so a script can swap them.
    """
    layers = [{"slot": "base", "url": av.asset_url("locations/avatar/base.png")}]
    for slot in av.SLOTS:
        key = (equipped or {}).get(slot, "")
        item = av.find_item(slot, key)
        if item:
            layers.append({"slot": slot, "url": av.asset_url(item.file)})
        elif preview:
            layers.append({"slot": slot, "url": ""})
    focus = av.BUST if view == "bust" else None
    return _picture(layers, focus, label, css_class, preview)


@register.inclusion_tag("locations/_avatar.html")
def avatar_item(item):
    """The bare raccoon wearing one accessory, zoomed in on it. Used for the tiles of the wardrobe."""
    layers = [
        {"slot": "base", "url": av.asset_url("locations/avatar/base.png")},
        {"slot": item.slot, "url": av.asset_url(item.file)},
    ]
    return _picture(layers, item.focus)
