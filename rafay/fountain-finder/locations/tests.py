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
