from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import CheckIn, UserProfile
from .achievements import unlock_achievements


@transaction.atomic
def check_in(user, facility):
    """Record one daily visit and update the balance in the same transaction."""
    profile, _ = UserProfile.objects.get_or_create(user=user)
    now = timezone.now()
    visit, created = CheckIn.objects.get_or_create(
        user=user, facility=facility, visit_date=timezone.localdate(now),
        defaults={"visited_at": now, "points_awarded": 10},
    )
    if created:
        UserProfile.objects.filter(pk=profile.pk).update(
            total_points=F("total_points") + visit.points_awarded
        )
    profile.refresh_from_db()
    # Keep the existing three-value return contract for HTML callers.
    visit.new_achievements = unlock_achievements(user) if created else []
    return visit, created, profile
