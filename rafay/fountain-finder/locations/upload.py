"""Server-to-server facility uploads; the token belongs only on trusted servers."""
import json
import math
import re

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.utils.crypto import constant_time_compare
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .api import FacilityForm, serialize_facility


FLOOR_RE = re.compile(r"[A-Za-z]?[0-9]+")


@csrf_exempt  # Uses an explicit shared secret, never session-cookie authentication.
@never_cache
@require_POST
def create_facility(request):
    expected = settings.UPLOAD_TOKEN
    if not expected:
        return JsonResponse({"error": "Uploads are disabled: UPLOAD_TOKEN is not set on the server."}, status=503)
    given = request.headers.get("X-Upload-Token", "")
    if not constant_time_compare(given, expected):
        return JsonResponse({"error": "Invalid upload token."}, status=401)
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "Body must be valid JSON."}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({"error": "Body must be a JSON object."}, status=400)
    if set(data) - {"latitude", "longitude", "building", "floor", "accessible"}:
        return JsonResponse({"error": "Only location, building, floor and accessibility fields are accepted."}, status=400)
    for field in ("latitude", "longitude"):
        value = data.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return JsonResponse({"error": f"Valid {field} is required."}, status=400)
    building = data.get("building")
    if not isinstance(building, str) or not building.strip() or len(building.strip()) > 200:
        return JsonResponse({"error": "A building (up to 200 characters) is required."}, status=400)
    floor = data.get("floor", "")
    if type(floor) is int:
        floor = str(floor)
    if not isinstance(floor, str) or not FLOOR_RE.fullmatch(floor.strip()):
        return JsonResponse({"error": "Floor must be a number or a letter and a number, like 2 or M2."}, status=400)
    form = FacilityForm({
        "name": "pending", "facility_type": "fountain",
        "building": building.strip(), "floor": floor.strip().upper(),
        "latitude": data["latitude"], "longitude": data["longitude"],
        "accessible": data.get("accessible") is True,
    })
    if not form.is_valid():
        return JsonResponse({"errors": form.errors.get_json_data()}, status=400)
    # Allocate the ID in the database, then name it in the same transaction.
    # Unlike count()+1, this works across processes and after deletions.
    with transaction.atomic():
        facility = form.save()
        facility.name = f"f{facility.pk}"
        facility.save(update_fields=["name"])
    return JsonResponse(serialize_facility(facility), status=201)
