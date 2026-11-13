from django.contrib import admin
from .models import Facility

@admin.register(Facility)
class FacilityAdmin(admin.ModelAdmin):
    list_display = (
        "building",
        "floor",
        "accessible"
    )

    list_filter = ("facility_type", "accessible")
    search_fields = ("name", "building")
