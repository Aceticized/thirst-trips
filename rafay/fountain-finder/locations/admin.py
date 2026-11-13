from django.contrib import admin

from .models import CheckIn, Facility, UserProfile


@admin.register(Facility)
class FacilityAdmin(admin.ModelAdmin):
    list_display = (
        "id", "name", "facility_type", "building", "floor", "accessible", "nfc_id",
    )
    search_fields = ("name", "building", "nfc_id")
    list_filter = ("facility_type", "building", "accessible")
    readonly_fields = ("nfc_id",)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "total_points")
    search_fields = ("user__username",)
    list_select_related = ("user",)


@admin.register(CheckIn)
class CheckInAdmin(admin.ModelAdmin):
    list_display = ("user", "facility", "visited_at", "points_awarded")
    list_filter = ("visited_at",)
    list_select_related = ("user", "facility")
    readonly_fields = ("visited_at",)
