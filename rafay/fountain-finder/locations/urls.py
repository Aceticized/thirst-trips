from django.urls import path
from . import api
from .upload import create_facility
from .views import nearby_facilities, profile

urlpatterns = [
    path("facilities/create/", create_facility, name="create-facility"),
    path("auth/csrf/", api.csrf),
    path("auth/register/", api.register),
    path("auth/login/", api.sign_in),
    path("auth/logout/", api.sign_out),
    path("me/", api.me),
    path("facilities/", api.facilities),
    path("facilities/<int:pk>/", api.facility_detail),
    path("checkin/", api.confirm_check_in),
    path("users/<int:user_id>/points/", api.adjust_points),
    path("profile/", profile, name="profile"),
    path("nearby/", nearby_facilities),
]