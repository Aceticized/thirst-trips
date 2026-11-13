"""
POST /api/facilities/create/  - lets the uploader add a new water fountain.

Copy this file to  locations/upload.py  in the Django project (see README.md).

The id is assigned HERE, not by the uploader: it is "number of existing entries + 1",
worked out and saved under a lock so two uploads can never be given the same id.
The primary key is also unique in the database, so even with several server
processes a clash is rejected and the id is recalculated instead of duplicated.
"""
import hmac
import json
import os
import re
import threading

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import Facility

FLOOR_RE = re.compile(r"^[A-Za-z]?\d+$")  # a number, or a letter then a number (2, M2)
_create_lock = threading.Lock()


def _error(message, status):
    return JsonResponse({"error": message}, status=status)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


@csrf_exempt  # called server-to-server by the uploader, which has no CSRF cookie
@require_POST
def create_facility(request):
    # Anyone who knows the public URL could otherwise write to the database,
    # so the uploader must send the shared secret in the X-Upload-Token header.
    expected = os.environ.get("UPLOAD_TOKEN")
    if not expected:
        return _error("Uploads are disabled: UPLOAD_TOKEN is not set on the server.", 503)
    given = request.headers.get("X-Upload-Token", "")
    if not hmac.compare_digest(given.encode(), expected.encode()):
        return _error("Invalid upload token.", 401)

    try:
        data = json.loads(request.body)
    except ValueError:
        return _error("Body must be valid JSON.", 400)
    if not isinstance(data, dict):
        return _error("Body must be a JSON object.", 400)

    lat, lon = data.get("latitude"), data.get("longitude")
    if not (_is_number(lat) and _is_number(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        return _error("Valid latitude and longitude are required.", 400)

    building = str(data.get("building") or "").strip()
    if not building or len(building) > 200:
        return _error("A building (up to 200 characters) is required.", 400)

    floor = str(data.get("floor") or "").strip().upper()
    if not FLOOR_RE.match(floor):
        return _error("Floor must be a number or a letter and a number, like 2 or M2.", 400)

    accessible = data.get("accessible") is True

    with _create_lock:
        new_id = Facility.objects.count() + 1
        for _ in range(5):
            try:
                with transaction.atomic():
                    facility = Facility.objects.create(
                        id=new_id,
                        name=f"f{new_id}",
                        facility_type="fountain",
                        building=building,
                        floor=floor,
                        latitude=lat,
                        longitude=lon,
                        accessible=accessible,
                    )
                break
            except IntegrityError:
                # That id is already used (e.g. an entry was deleted earlier): take the next free one.
                new_id = (Facility.objects.aggregate(top=Max("id"))["top"] or 0) + 1
        else:
            return _error("Could not assign an id, please try again.", 503)

    return JsonResponse(
        {
            "id": facility.id,
            "name": facility.name,
            "facility_type": facility.facility_type,
            "building": facility.building,
            "floor": facility.floor,
            "latitude": facility.latitude,
            "longitude": facility.longitude,
            "accessible": facility.accessible,
        },
        status=201,
    )
