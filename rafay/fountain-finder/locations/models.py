from django.db import models

class Facility(models.Model):
    FACILITY_TYPES = [
        ("washroom", "Washroom"),
        ("fountain", "Water Fountain"),
    ]

    name = models.CharField(max_length=200)
    facility_type = models.CharField(
        max_length=20,
        choices=FACILITY_TYPES
    )

    latitude = models.FloatField()
    longitude = models.FloatField()

    building = models.CharField(
        max_length=200, blank=True
    )
    floor = models.IntegerField(
        null=True, blank=True
    )
    accessible = models.BooleanField(default=False)

    def __str__(self):
        return self.name