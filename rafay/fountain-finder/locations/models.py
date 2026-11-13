import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class Facility(models.Model):
    class Type(models.TextChoices):
        FOUNTAIN = "fountain", "Water fountain"
        WASHROOM = "washroom", "Washroom"

    nfc_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=100)
    facility_type = models.CharField(
        max_length=20, choices=Type.choices, default=Type.FOUNTAIN
    )
    building = models.CharField(max_length=200)
    floor = models.CharField(max_length=20, blank=True)
    latitude = models.FloatField(
        validators=[MinValueValidator(-90), MaxValueValidator(90)]
    )
    longitude = models.FloatField(
        validators=[MinValueValidator(-180), MaxValueValidator(180)]
    )
    accessible = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name} - {self.building}"


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    total_points = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.user} ({self.total_points} points)"


class CheckIn(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="check_ins"
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="check_ins"
    )
    visited_at = models.DateTimeField(default=timezone.now, editable=False)
    visit_date = models.DateField(default=timezone.localdate, editable=False)
    points_awarded = models.PositiveIntegerField(default=10)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "facility", "visit_date"], name="one_daily_facility_checkin")
        ]
        ordering = ["-visited_at"]
        indexes = [models.Index(fields=["user", "facility", "visited_at"])]

    def __str__(self):
        return f"{self.user} visited {self.facility} at {self.visited_at}"
