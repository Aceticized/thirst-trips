
import uuid
from django.db import models


class Facility(models.Model):
    FACILITY_TYPES = [
        ("fountain", "Water Fountain"),
        ("washroom", "Washroom"),
    ]

    # Automatically generated unique NFC identifier
    nfc_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False
    )

    name = models.CharField(max_length=100)

    facility_type = models.CharField(
        max_length=20,
        choices=FACILITY_TYPES,
        default="fountain"
    )

    building = models.CharField(max_length=100)

    floor = models.CharField(max_length=20)

    latitude = models.FloatField()
    longitude = models.FloatField()

    accessible = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name} - {self.building} (Floor {self.floor})"
