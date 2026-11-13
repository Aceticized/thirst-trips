import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from .models import CheckIn, Facility, UserProfile


class JsonApiTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(username="staff", is_staff=True)
        self.user = get_user_model().objects.create_user(username="visitor", password="River!Fountain372")
        self.data = {"name": "Library fountain", "building": "Library", "latitude": 53.5, "longitude": -113.5}
        self.facility = Facility.objects.create(**self.data)

    def post(self, url, data):
        return self.client.post(url, json.dumps(data), content_type="application/json")

    def test_registration_and_login(self):
        response = self.post("/api/auth/register/", {
            "username": "new-user", "password1": "Fountain!River792", "password2": "Fountain!River792",
        })
        self.assertEqual(response.status_code, 201)
        user = get_user_model().objects.get(username="new-user")
        self.assertTrue(user.check_password("Fountain!River792"))
        self.assertEqual(user.profile.total_points, 0)
        self.assertIn("csrfToken", response.json())
        self.assertEqual(self.client.get("/api/me/").json()["id"], user.pk)
        self.assertEqual(self.post("/api/auth/logout/", {}).status_code, 200)
        self.assertEqual(self.client.get("/api/me/").status_code, 401)
        self.assertEqual(self.post("/api/auth/login/", {"username": "new-user", "password": "wrong"}).status_code, 401)
        self.assertEqual(self.post("/api/auth/login/", {"username": "new-user", "password": "Fountain!River792"}).status_code, 200)

    def test_registration_rejects_privilege_fields_and_invalid_values(self):
        self.assertEqual(self.post("/api/auth/register/", {"username": "admin", "is_staff": True}).status_code, 400)
        self.assertEqual(self.post("/api/auth/register/", {"username": []}).status_code, 400)
        self.assertEqual(self.post("/api/auth/register/", {"username": "visitor", "password1": "123", "password2": "123"}).status_code, 400)
        self.assertEqual(get_user_model().objects.count(), 2)

    def test_facility_reads_and_staff_crud(self):
        self.assertEqual(self.client.get("/api/facilities/").status_code, 200)
        self.assertNotIn("nfc_id", self.client.get(f"/api/facilities/{self.facility.pk}/").json())
        self.assertEqual(self.post("/api/facilities/", self.data).status_code, 401)
        self.client.force_login(self.user)
        self.assertEqual(self.post("/api/facilities/", self.data).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/facilities/{self.facility.pk}/").status_code, 403)
        self.client.force_login(self.staff)
        response = self.post("/api/facilities/", self.data)
        self.assertEqual(response.status_code, 201)
        pk = response.json()["id"]
        response = self.client.patch(f"/api/facilities/{pk}/", json.dumps({"name": "Updated", "accessible": True}), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Updated")
        self.assertTrue(response.json()["accessible"])
        self.assertEqual(self.client.delete(f"/api/facilities/{pk}/").status_code, 200)
        CheckIn.objects.create(user=self.user, facility=self.facility)
        self.assertEqual(self.client.delete(f"/api/facilities/{self.facility.pk}/").status_code, 409)

    def test_facility_validation(self):
        self.client.force_login(self.staff)
        for changes in ({"latitude": 91}, {"longitude": float("nan")}, {"accessible": "false"}, {"name": []}, {"nfc_id": "custom"}):
            self.assertEqual(self.post("/api/facilities/", {**self.data, **changes}).status_code, 400)

    def test_server_controlled_checkin_points(self):
        token = {"token": str(self.facility.nfc_id)}
        self.assertEqual(self.post("/api/checkin/", token).status_code, 401)
        self.client.force_login(self.user)
        self.assertEqual(self.post("/api/checkin/", {**token, "points": 999}).status_code, 400)
        self.assertEqual(self.post("/api/checkin/", {"token": "bad"}).status_code, 400)
        self.assertEqual(self.post("/api/checkin/", token).status_code, 201)
        response = self.post("/api/checkin/", token)
        self.assertEqual(response.json()["points_awarded"], 0)
        self.assertEqual(response.json()["total_points"], 10)
        self.assertEqual(CheckIn.objects.count(), 1)

    def test_only_staff_can_adjust_points(self):
        url = f"/api/users/{self.user.pk}/points/"
        self.assertEqual(self.post(url, {"delta": 50}).status_code, 401)
        self.client.force_login(self.user)
        self.assertEqual(self.post(url, {"delta": 50}).status_code, 403)
        self.client.force_login(self.staff)
        self.assertEqual(self.post(url, {"delta": 50}).json()["total_points"], 50)
        self.assertEqual(self.post(url, {"delta": -20}).json()["total_points"], 30)
        self.assertEqual(self.post(url, {"delta": -31}).status_code, 400)
        self.assertEqual(self.post(url, {"delta": True}).status_code, 400)
        self.assertEqual(UserProfile.objects.get(user=self.user).total_points, 30)

    def test_json_validation(self):
        self.assertEqual(self.client.post("/api/auth/register/", "{bad", content_type="application/json").status_code, 400)
        self.assertEqual(self.post("/api/auth/register/", []).status_code, 400)
        self.assertEqual(self.client.post("/api/auth/register/", {}).status_code, 415)

    def test_real_csrf_cookie_session_flow(self):
        client = Client(enforce_csrf_checks=True)
        payload = {"username": "visitor", "password": "River!Fountain372"}
        self.assertEqual(client.post("/api/auth/login/", json.dumps(payload), content_type="application/json").status_code, 403)
        token = client.get("/api/auth/csrf/").json()["csrfToken"]
        response = client.post("/api/auth/login/", json.dumps(payload), content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200)
        rotated_token = response.json()["csrfToken"]
        self.assertNotEqual(token, rotated_token)
        response = client.post("/api/checkin/", json.dumps({"token": str(self.facility.nfc_id)}), content_type="application/json", HTTP_X_CSRFTOKEN=rotated_token)
        self.assertEqual(response.status_code, 201)


class FrontendOriginTests(TestCase):
    def test_approved_origin_preflight(self):
        response = self.client.options(
            "/api/facilities/", HTTP_ORIGIN="https://thirsttrips-ua.ca",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type,x-csrftoken",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Access-Control-Allow-Origin"], "https://thirsttrips-ua.ca")
        self.assertEqual(response["Access-Control-Allow-Credentials"], "true")
        self.assertIn("x-csrftoken", response["Access-Control-Allow-Headers"])

    def test_unapproved_origins_and_admin_not_enabled(self):
        response = self.client.get("/api/facilities/", HTTP_ORIGIN="https://example.com")
        self.assertNotIn("Access-Control-Allow-Origin", response)
        response = self.client.get("/admin/login/", HTTP_ORIGIN="https://thirsttrips-ua.ca")
        self.assertNotIn("Access-Control-Allow-Origin", response)

    def test_csrf_accepts_frontend_origin_with_valid_token(self):
        client = Client(enforce_csrf_checks=True)
        token = client.get("/api/auth/csrf/", HTTP_ORIGIN="https://thirsttrips-ua.ca").json()["csrfToken"]
        response = client.post("/api/auth/login/", json.dumps({"username": "none", "password": "none"}),
                               content_type="application/json", HTTP_ORIGIN="https://thirsttrips-ua.ca",
                               HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 401)  # Authentication reached; no CSRF rejection.
        response = client.post("/api/auth/login/", "{}", content_type="application/json",
                               HTTP_ORIGIN="https://example.com", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 403)
