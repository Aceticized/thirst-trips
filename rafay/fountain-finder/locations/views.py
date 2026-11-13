from django.http import JsonResponse
from .models import Facility
from .utils import calculate_distance

def nearby_facilities(request):
    try:
        lat = float(request.GET["lat"])
        lon = float(request.GET["lon"])
    except (KeyError, ValueError):
        return JsonResponse(
            {"error": "Valid lat and lon required"},
            status=400
        )

    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return JsonResponse(
            {"error": "Coordinates out of range"},
            status=400
        )

    facility_type = request.GET.get("type")
    facilities = Facility.objects.all()

    if facility_type:
        if facility_type not in ("washroom", "fountain"):
            return JsonResponse(
                {"error": "Invalid facility type"},
                status=400
            )
        facilities = facilities.filter(
            facility_type=facility_type
        )

    results = []

    for facility in facilities:
        distance = calculate_distance(
            lat, lon,
            facility.latitude,
            facility.longitude
        )

        results.append({
            "id": facility.id,
            "name": facility.name,
            "type": facility.facility_type,
            "latitude": facility.latitude,
            "longitude": facility.longitude,
            "distance_m": round(distance),
            "accessible": facility.accessible
        })

    results.sort(key=lambda x: x["distance_m"])

    return JsonResponse({"facilities": results[:10]})
