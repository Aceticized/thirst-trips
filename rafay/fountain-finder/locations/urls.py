from django.urls import path
from .views import nearby_facilities, profile

urlpatterns = [
    path("profile/", profile, name="profile"),
    path("nearby/", nearby_facilities),
]