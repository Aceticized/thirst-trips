"""JSON endpoints using Django sessions and CSRF protection."""
import json
import math
from functools import wraps

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.forms import UserCreationForm
from django.db import IntegrityError, transaction
from django.db.models import F
from django.db.models.deletion import ProtectedError
from django.forms import modelform_factory
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .models import Facility, UserProfile, UserAchievement
from django.utils import timezone
from .achievements import unlock_achievements
from .services import check_in
from .achievements import achievement_status


FACILITY_FIELDS = (
    "name", "facility_type", "building", "floor", "latitude", "longitude", "accessible",
)
FacilityForm = modelform_factory(Facility, fields=FACILITY_FIELDS)


def endpoint(methods, *, authenticated=False, staff=False):
    def decorate(view):
        @never_cache
        @require_http_methods(methods)
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if (authenticated or staff) and not request.user.is_authenticated:
                return JsonResponse({"error": "Login required"}, status=401)
            if staff and not request.user.is_staff:
                return JsonResponse({"error": "Staff access required"}, status=403)
            if request.method in {"POST", "PATCH", "PUT"}:
                if request.content_type != "application/json":
                    return JsonResponse({"error": "Use application/json"}, status=415)
                try:
                    request.payload = json.loads(request.body)
                except (ValueError, UnicodeDecodeError):
                    return JsonResponse({"error": "Invalid JSON"}, status=400)
                if not isinstance(request.payload, dict):
                    return JsonResponse({"error": "Expected a JSON object"}, status=400)
            return view(request, *args, **kwargs)
        return wrapped
    return decorate


def serialize_facility(facility):
    return {"id": facility.pk, **{field: getattr(facility, field) for field in FACILITY_FIELDS}}


def account_data(user):
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return {"id": user.pk, "username": user.get_username(),
            "total_points": profile.total_points, "is_staff": user.is_staff}


@endpoint(["GET"])
def csrf(request):
    return JsonResponse({"csrfToken": get_token(request)})


@endpoint(["POST"])
def register(request):
    if request.user.is_authenticated:
        return JsonResponse({"error": "Log out before registering another account"}, status=400)
    if set(request.payload) - {"username", "password1", "password2"}:
        return JsonResponse({"error": "Only username, password1 and password2 are accepted"}, status=400)
    if any(not isinstance(v, str) for v in request.payload.values()):
        return JsonResponse({"error": "Account fields must be strings"}, status=400)
    form = UserCreationForm(request.payload)
    if not form.is_valid():
        return JsonResponse({"errors": form.errors.get_json_data()}, status=400)
    try:
        with transaction.atomic():
            user = form.save()
            UserProfile.objects.create(user=user)
    except IntegrityError:
        return JsonResponse({"error": "Username unavailable"}, status=409)
    login(request, user)
    return JsonResponse({**account_data(user), "csrfToken": get_token(request)}, status=201)


@endpoint(["POST"])
def sign_in(request):
    username = request.payload.get("username")
    password = request.payload.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        return JsonResponse({"error": "Username and password required"}, status=400)
    user = authenticate(request, username=username, password=password)
    if user is None:
        return JsonResponse({"error": "Invalid username or password"}, status=401)
    login(request, user)
    return JsonResponse({**account_data(user), "csrfToken": get_token(request)})


@endpoint(["POST"], authenticated=True)
def sign_out(request):
    logout(request)
    return JsonResponse({"success": True})


@endpoint(["GET"], authenticated=True)
def me(request):
    return JsonResponse(account_data(request.user))


@endpoint(["GET"], authenticated=True)
def achievements(request):
    return JsonResponse({"achievements": achievement_status(request.user)})


@endpoint(["POST"], authenticated=True)
def claim_achievement_notifications(request):
    """Atomically consume each notification, including across tabs and devices."""
    notifications = []
    status = {item["code"]: item for item in achievement_status(request.user)}
    with transaction.atomic():
        for award in UserAchievement.objects.filter(user=request.user, notification_seen_at__isnull=True):
            claimed = UserAchievement.objects.filter(pk=award.pk, notification_seen_at__isnull=True).update(
                notification_seen_at=timezone.now()
            )
            if claimed and award.code in status:
                notifications.append(status[award.code])
    return JsonResponse({"notifications": notifications})


@endpoint(["POST"], authenticated=True)
def discover_facility(request):
    """Credit the authenticated contributor, never a client-supplied user ID."""
    with transaction.atomic():
        if request.payload.get("facility_type", "fountain") != "fountain":
            return JsonResponse({"error": "Only fountain discoveries are accepted"}, status=400)
        # Reject exact resubmissions; nearby distinct fountains remain allowed.
        lat, lon = request.payload.get("latitude"), request.payload.get("longitude")
        if type(lat) in (int, float) and type(lon) in (int, float) and math.isfinite(lat) and math.isfinite(lon):
            if Facility.objects.filter(latitude=lat, longitude=lon,
                                       floor=request.payload.get("floor", ""),
                                       facility_type="fountain").exists():
                return JsonResponse({"error": "A fountain at these coordinates and floor already exists"}, status=409)
        response = save_facility(request)
        if response.status_code != 201:
            return response
        data = json.loads(response.content)
        facility = Facility.objects.get(pk=data["id"])
        facility.discovered_by = request.user
        facility.save(update_fields=["discovered_by"])
        data["new_achievements"] = unlock_achievements(request.user)
    return JsonResponse(data, status=201)


def save_facility(request, instance=None):
    data = request.payload
    if set(data) - set(FACILITY_FIELDS):
        return JsonResponse({"error": "Unknown or read-only facility fields"}, status=400)
    for field, value in data.items():
        if field in {"latitude", "longitude"}:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                return JsonResponse({"error": f"{field} must be a finite number"}, status=400)
        elif field == "accessible":
            if not isinstance(value, bool):
                return JsonResponse({"error": "accessible must be a boolean"}, status=400)
        elif not isinstance(value, str):
            return JsonResponse({"error": f"{field} must be a string"}, status=400)
    values = {field: getattr(instance, field) for field in FACILITY_FIELDS} if instance else {
        "facility_type": Facility.Type.FOUNTAIN, "accessible": False,
    }
    form = FacilityForm({**values, **data}, instance=instance)
    if not form.is_valid():
        return JsonResponse({"errors": form.errors.get_json_data()}, status=400)
    facility = form.save()
    return JsonResponse(serialize_facility(facility), status=200 if instance else 201)


@endpoint(["GET", "POST"])
def facilities(request):
    if request.method == "GET":
        return JsonResponse({"facilities": [serialize_facility(f) for f in Facility.objects.order_by("pk")]})
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Login required"}, status=401)
    if not request.user.is_staff:
        return JsonResponse({"error": "Staff access required"}, status=403)
    return save_facility(request)


@endpoint(["GET", "PATCH", "DELETE"])
def facility_detail(request, pk):
    if request.method != "GET":
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Login required"}, status=401)
        if not request.user.is_staff:
            return JsonResponse({"error": "Staff access required"}, status=403)
    facility = get_object_or_404(Facility, pk=pk)
    if request.method == "GET":
        return JsonResponse(serialize_facility(facility))
    if request.method == "PATCH":
        return save_facility(request, facility)
    try:
        facility.delete()
    except ProtectedError:
        return JsonResponse({"error": "Facilities with check-ins cannot be deleted"}, status=409)
    return JsonResponse({"success": True})


@endpoint(["POST"], authenticated=True)
def confirm_check_in(request):
    from uuid import UUID
    try:
        token = UUID(request.payload.get("token", ""))
    except (ValueError, TypeError, AttributeError):
        return JsonResponse({"error": "A valid NFC token is required"}, status=400)
    if set(request.payload) != {"token"}:
        return JsonResponse({"error": "Only the NFC token is accepted; points are set by the server"}, status=400)
    facility = get_object_or_404(Facility, nfc_id=token)
    visit, created, profile = check_in(request.user, facility)
    return JsonResponse({"check_in_id": visit.pk, "created": created,
                         "points_awarded": visit.points_awarded if created else 0,
                         "total_points": profile.total_points,
                         "new_achievements": visit.new_achievements}, status=201 if created else 200)


@endpoint(["POST"], staff=True)
def adjust_points(request, user_id):
    delta = request.payload.get("delta")
    if set(request.payload) != {"delta"} or type(delta) is not int or not -1000000 <= delta <= 1000000:
        return JsonResponse({"error": "Provide an integer delta between -1000000 and 1000000"}, status=400)
    user = get_object_or_404(get_user_model(), pk=user_id)
    with transaction.atomic():
        profile, _ = UserProfile.objects.get_or_create(user=user)
        updated = UserProfile.objects.filter(
            pk=profile.pk, total_points__gte=max(0, -delta),
            total_points__lte=2147483647 - max(0, delta),
        ).update(total_points=F("total_points") + delta)
        if not updated:
            return JsonResponse({"error": "Adjustment would put points outside the supported range"}, status=400)
        profile.refresh_from_db()
    return JsonResponse({"user_id": user.pk, "total_points": profile.total_points})
