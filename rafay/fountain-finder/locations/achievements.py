"""Server-owned achievement rules shared by HTML and JSON check-ins."""
from django.db.models import Sum

from .models import CheckIn, Facility, UserAchievement


ACHIEVEMENTS = (
    {"code": "new_fountain", "name": "Fountain Finder",
     "description": "Add your first new fountain.", "metric": "discovered_fountains", "target": 1},
    {"code": "first_check_in", "name": "First Sip",
     "description": "Complete your first check-in.", "metric": "check_ins", "target": 1},
    {"code": "points_50", "name": "Getting Hydrated",
     "description": "Earn 50 points from check-ins.", "metric": "earned_points", "target": 50},
    {"code": "fountains_5", "name": "Fountain Explorer",
     "description": "Check in at 5 different water fountains.", "metric": "distinct_fountains", "target": 5},
)


def progress_for(user):
    visits = CheckIn.objects.filter(user=user)
    return {
        "discovered_fountains": Facility.objects.filter(discovered_by=user, facility_type=Facility.Type.FOUNTAIN).count(),
        "check_ins": visits.count(),
        "earned_points": visits.aggregate(total=Sum("points_awarded"))["total"] or 0,
        "distinct_fountains": visits.filter(facility__facility_type=Facility.Type.FOUNTAIN)
        .values("facility_id").distinct().count(),
    }


def serialize_achievement(definition, award, progress):
    return {
        **definition,
        "progress": min(progress[definition["metric"]], definition["target"]),
        "unlocked": award is not None,
        "unlocked_at": award.unlocked_at.isoformat() if award else None,
    }


def achievement_status(user):
    """Read progress without creating awards or modifying the user's account."""
    progress = progress_for(user)
    awards = {award.code: award for award in UserAchievement.objects.filter(user=user)}
    return [serialize_achievement(item, awards.get(item["code"]), progress)
            for item in ACHIEVEMENTS]


def unlock_achievements(user):
    """Called inside the check-in transaction; uniqueness prevents duplicate awards."""
    progress = progress_for(user)
    newly_unlocked = []
    for item in ACHIEVEMENTS:
        if progress[item["metric"]] >= item["target"]:
            award, created = UserAchievement.objects.get_or_create(user=user, code=item["code"])
            if created:
                newly_unlocked.append(serialize_achievement(item, award, progress))
    return newly_unlocked
