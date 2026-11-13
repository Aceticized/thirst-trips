from django.urls import path
from .views import nearby_facilities

urlpatterns = [
    path("nearby/", nearby_facilities),
]