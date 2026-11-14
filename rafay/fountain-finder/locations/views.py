from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from .forms import SignupForm
from django.views.decorators.http import require_GET, require_http_methods
from django.views.decorators.cache import never_cache
from django.shortcuts import get_object_or_404, redirect, render
from .services import check_in
from django.http import JsonResponse
from .models import CheckIn, Facility, UserProfile
from django.utils import timezone
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


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def facility_check_in(request, token):
    facility = get_object_or_404(Facility, nfc_id=token)
    if request.method == "POST":
        visit, created, user_profile = check_in(request.user, facility)
        return redirect("check-in", token=facility.nfc_id)
    user_profile, _ = UserProfile.objects.get_or_create(user=request.user)
    visit = CheckIn.objects.filter(
        user=request.user, facility=facility, visit_date=timezone.localdate()
    ).first()
    return render(request, "locations/check_in.html", {
        "facility": facility, "visit": visit, "profile": user_profile,
    })


@never_cache
@require_http_methods(["GET", "POST"])
def signup(request, default_destination="profile", login_url_name="login"):
    from django.contrib.auth import login
    from django.db import transaction
    from django.utils.http import url_has_allowed_host_and_scheme

    destination = request.POST.get("next", request.GET.get("next", ""))
    if not url_has_allowed_host_and_scheme(
        destination, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        destination = ""
    if request.user.is_authenticated:
        return redirect(destination or default_destination)
    form = SignupForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = form.save()
            UserProfile.objects.create(user=user)
        login(request, user)
        return redirect(destination or default_destination)
    return render(request, "registration/signup.html", {
        "form": form, "next": destination, "login_url": reverse(login_url_name),
    })


@login_required(login_url="login-page")
@never_cache
@require_GET
def account(request):
    """Landing page after logging in without an NFC tag (the /login/ page)."""
    user_profile, _ = UserProfile.objects.get_or_create(user=request.user)
    return render(request, "locations/account.html", {
        "profile": user_profile, "home_url": settings.HOME_URL,
    })
