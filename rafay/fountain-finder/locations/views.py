
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET
from django.http import JsonResponse
from .models import Facility, UserProfile
from .utils import haversine


def nearby_facilities(request):
    # Get user's coordinates
    try:
        user_lat = float(request.GET.get("lat"))
        user_lon = float(request.GET.get("lon"))
    except (TypeError, ValueError):
        return JsonResponse(
            {"error": "Valid lat and lon parameters are required"},
            status=400
        )

    # Retrieve all fountains
    fountains = Facility.objects.all()

    results = []

    for fountain in fountains:
        # Calculate distance from user to fountain
        distance = haversine(
            user_lat,
            user_lon,
            fountain.latitude,
            fountain.longitude
        )

        results.append({
            "id": fountain.id,
            "name": fountain.name,
            "facility_type": fountain.facility_type,
            "building": fountain.building,
            "floor": fountain.floor,
            "latitude": fountain.latitude,
            "longitude": fountain.longitude,
            "accessible": fountain.accessible,
            "distance_m": round(distance, 1)
        })

    # Sort fountains from nearest to farthest
    results.sort(key=lambda x: x["distance_m"])

    return JsonResponse({"facilities": results})


@login_required
@require_GET
def profile(request):
    """Return only the authenticated user's points; clients cannot select a user."""
    user_profile, _ = UserProfile.objects.get_or_create(user=request.user)
    response = JsonResponse({
        "username": request.user.get_username(),
        "total_points": user_profile.total_points,
    })
    response["Cache-Control"] = "no-store"
    return response
