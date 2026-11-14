from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from .models import CheckIn, Facility, UserProfile


class FacilityModelTests(TestCase):
    def setUp(self):
        self.facility = Facility.objects.create(
            name="Library fountain", building="Library",
            latitude=53.5, longitude=-113.5,
        )

    def test_unique_nfc_and_default_type(self):
        other = Facility.objects.create(
            name="Washroom", building="Library", facility_type=Facility.Type.WASHROOM,
            latitude=53.5, longitude=-113.5,
        )
        self.assertNotEqual(self.facility.nfc_id, other.nfc_id)
        self.assertEqual(self.facility.facility_type, Facility.Type.FOUNTAIN)

    def test_coordinate_validation(self):
        self.facility.latitude = 91
        with self.assertRaises(ValidationError):
            self.facility.full_clean()

    def test_check_in_history_and_profile(self):
        user = get_user_model().objects.create_user(username="visitor")
        profile = UserProfile.objects.create(user=user)
        visit = CheckIn.objects.create(user=user, facility=self.facility)
        self.assertEqual(profile.total_points, 0)
        self.assertEqual(visit.points_awarded, 10)
        self.assertIsNotNone(visit.visited_at)
        self.assertEqual(user.check_ins.get(), visit)
        with self.assertRaises(ProtectedError):
            self.facility.delete()


class ProfileAccessTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="alice", password="test-password-123"
        )

    def test_anonymous_user_must_log_in(self):
        response = self.client.get("/api/profile/")
        self.assertRedirects(response, "/accounts/login/?next=/api/profile/")

    def test_login_returns_to_profile(self):
        response = self.client.post("/accounts/login/?next=/api/profile/", {
            "username": "alice", "password": "test-password-123",
            "next": "/api/profile/",
        })
        self.assertRedirects(response, "/api/profile/")
        self.assertEqual(self.client.get("/api/profile/").json()["total_points"], 0)

    def test_profile_cannot_access_other_users_points(self):
        other = get_user_model().objects.create_user(username="bob")
        UserProfile.objects.create(user=other, total_points=500)
        UserProfile.objects.create(user=self.user, total_points=20)
        self.client.force_login(self.user)
        response = self.client.get(f"/api/profile/?user_id={other.pk}")
        self.assertEqual(response.json(), {"username": "alice", "total_points": 20})
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_profile_does_not_accept_points_updates(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.post("/api/profile/", {"total_points": 999}).status_code, 405)

    def test_logout_removes_access(self):
        self.client.force_login(self.user)
        self.client.post("/accounts/logout/")
        self.assertEqual(self.client.get("/api/profile/").status_code, 302)


class CheckInFlowTests(TestCase):
    def setUp(self):
        from django.urls import reverse
        self.user = get_user_model().objects.create_user(username="scanner", password="password-123")
        self.facility = Facility.objects.create(
            name="Test fountain", building="Library", latitude=53, longitude=-113,
        )
        self.url = reverse("check-in", kwargs={"token": self.facility.nfc_id})

    def test_login_preserves_destination(self):
        self.assertRedirects(self.client.get(self.url), f"/accounts/login/?next={self.url}")
        response = self.client.post("/accounts/login/", {
            "username": "scanner", "password": "password-123", "next": self.url,
        })
        self.assertRedirects(response, self.url)
        self.assertFalse(CheckIn.objects.exists())

    def test_confirmation_awards_points_only_once(self):
        self.client.force_login(self.user)
        self.assertContains(self.client.get(self.url), "Confirm check-in")
        self.assertFalse(CheckIn.objects.exists())
        self.assertRedirects(self.client.post(self.url), self.url)
        self.client.post(self.url)
        self.assertEqual(CheckIn.objects.count(), 1)
        self.assertEqual(UserProfile.objects.get(user=self.user).total_points, 10)
        self.assertContains(self.client.get(self.url), "checked in here today")

    def test_csrf_required(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.url).status_code, 403)
        self.assertFalse(CheckIn.objects.exists())

    def test_new_day_and_other_user_can_earn_points(self):
        from datetime import timedelta
        from django.utils import timezone
        CheckIn.objects.create(user=self.user, facility=self.facility,
                               visit_date=timezone.localdate() - timedelta(days=1))
        UserProfile.objects.create(user=self.user, total_points=10)
        self.client.force_login(self.user)
        self.client.post(self.url)
        self.assertEqual(UserProfile.objects.get(user=self.user).total_points, 20)
        other = get_user_model().objects.create_user(username="other-scanner")
        self.client.force_login(other)
        self.client.post(self.url)
        self.assertEqual(UserProfile.objects.get(user=other).total_points, 10)

    def test_invalid_tag(self):
        import uuid
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(f"/checkin/{uuid.uuid4()}/").status_code, 404)

    def test_points_failure_rolls_back_visit(self):
        from unittest.mock import patch
        from .services import check_in
        UserProfile.objects.create(user=self.user)
        with patch("django.db.models.query.QuerySet.update", side_effect=RuntimeError("failure")):
            with self.assertRaises(RuntimeError):
                check_in(self.user, self.facility)
        self.assertFalse(CheckIn.objects.exists())
        self.assertEqual(UserProfile.objects.get(user=self.user).total_points, 0)


class SignupTests(TestCase):
    def signup(self, **overrides):
        data = {"username": "new-visitor", "password1": "Fountain!River728", "password2": "Fountain!River728"}
        data.update(overrides)
        return self.client.post("/accounts/signup/", data)

    def test_creates_user_with_hashed_password_profile_and_session(self):
        self.assertRedirects(self.signup(), "/api/profile/")
        user = get_user_model().objects.get(username="new-visitor")
        self.assertNotEqual(user.password, "Fountain!River728")
        self.assertTrue(user.check_password("Fountain!River728"))
        self.assertEqual(user.profile.total_points, 0)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(self.client.get("/api/profile/").json()["username"], user.username)
        self.client.post("/accounts/logout/")
        self.assertTrue(self.client.login(username=user.username, password="Fountain!River728"))

    def test_rejects_duplicate_username(self):
        get_user_model().objects.create_user(username="new-visitor")
        self.assertContains(self.signup(), "A user with that username already exists")
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_rejects_mismatch_and_weak_passwords(self):
        self.assertEqual(self.signup(password2="different").status_code, 200)
        self.assertEqual(self.signup(password1="123", password2="123").status_code, 200)
        self.assertFalse(get_user_model().objects.exists())

    def test_preserves_checkin_destination(self):
        import uuid
        target = f"/checkin/{uuid.uuid4()}/"
        response = self.signup(next=target)
        self.assertEqual(response.url, target)

    def test_rejects_external_redirect(self):
        self.assertRedirects(self.signup(next="https://example.com/"), "/api/profile/")

    def test_requires_csrf(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        response = client.post("/accounts/signup/", {"username": "bad-request"})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(get_user_model().objects.exists())


class DirectLoginPageTests(TestCase):
    """The /login/ and /signup/ pages work without an NFC tag."""

    def test_login_page_is_simple_and_styled(self):
        response = self.client.get("/login/")
        self.assertContains(response, "<h1>Log In</h1>", html=True)
        self.assertNotContains(response, "Log in to")
        self.assertContains(response, "Playpen Sans")
        self.assertContains(response, 'href="/signup/"')

    def test_nfc_login_page_links_to_its_own_signup(self):
        response = self.client.get("/accounts/login/?next=/checkin/abc/")
        self.assertContains(response, "<h1>Log In</h1>", html=True)
        self.assertContains(response, 'href="/accounts/signup/?next=/checkin/abc/"')

    def test_password_fields_get_a_show_button(self):
        self.assertContains(self.client.get("/login/"), 'class="reveal"', count=1)
        self.assertContains(self.client.get("/signup/"), 'class="reveal"', count=2)

    def test_login_goes_to_account_page(self):
        get_user_model().objects.create_user(username="walker", password="Fountain!River728")
        response = self.client.post("/login/", {"username": "walker", "password": "Fountain!River728"})
        self.assertRedirects(response, "/account/")
        self.assertContains(self.client.get("/account/"), "Hi, walker!")

    def test_wrong_password_shows_error(self):
        get_user_model().objects.create_user(username="walker", password="Fountain!River728")
        response = self.client.post("/login/", {"username": "walker", "password": "nope"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please enter a correct username and password")

    def test_signup_page_creates_account_and_lands_on_account_page(self):
        response = self.client.post("/signup/", {
            "username": "direct-user", "password1": "Fountain!River728", "password2": "Fountain!River728",
        })
        self.assertRedirects(response, "/account/")
        self.assertEqual(get_user_model().objects.get(username="direct-user").profile.total_points, 0)

    def test_account_page_requires_login(self):
        self.assertRedirects(self.client.get("/account/"), "/login/?next=/account/")

    def test_admin_uses_playpen_sans(self):
        self.assertContains(self.client.get("/admin/login/"), "Playpen Sans")
