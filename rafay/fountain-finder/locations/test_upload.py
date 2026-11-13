import json

from django.test import Client, TestCase, override_settings

from .models import Facility


@override_settings(UPLOAD_TOKEN="test-only-upload-secret")
class UploadTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.payload = {"building": "Library", "floor": "M2",
                        "latitude": 53.52, "longitude": -113.53, "accessible": True}

    def upload(self, payload=None, token="test-only-upload-secret"):
        return self.client.post("/api/facilities/create/", json.dumps(self.payload if payload is None else payload),
                                content_type="application/json", HTTP_X_UPLOAD_TOKEN=token)

    @override_settings(UPLOAD_TOKEN="")
    def test_disabled_without_secret(self):
        self.assertEqual(self.upload().status_code, 503)
        self.assertFalse(Facility.objects.exists())

    def test_requires_secret_even_with_session(self):
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.create_user(username="staff-upload", is_staff=True)
        self.client.force_login(user)
        self.assertEqual(self.upload(token="wrong").status_code, 401)
        self.assertEqual(self.client.post("/api/facilities/create/", "{}", content_type="application/json").status_code, 401)
        self.assertFalse(Facility.objects.exists())

    def test_bearer_upload_assigns_ids_and_preserves_floor(self):
        first = self.upload()
        second = self.upload()
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertNotEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(first.json()["name"], f'f{first.json()["id"]}')
        self.assertEqual(Facility.objects.get(pk=first.json()["id"]).floor, "M2")

    def test_client_cannot_assign_ids_or_invalid_coordinates(self):
        self.assertEqual(self.upload({**self.payload, "id": 123}).status_code, 400)
        self.assertEqual(self.upload({**self.payload, "latitude": 100}).status_code, 400)
        self.assertFalse(Facility.objects.exists())

    def test_invalid_json_and_method(self):
        response = self.client.post("/api/facilities/create/", "{bad", content_type="application/json",
                                    HTTP_X_UPLOAD_TOKEN="test-only-upload-secret")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get("/api/facilities/create/").status_code, 405)

    def test_floor_normalization_and_building_length(self):
        response = self.upload({**self.payload, "floor": " m2 ", "building": "B" * 200})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["floor"], "M2")
        self.assertEqual(self.upload({**self.payload, "floor": 2}).status_code, 201)
        for changes in ({"floor": "second"}, {"floor": True}, {"building": "B" * 201}):
            self.assertEqual(self.upload({**self.payload, **changes}).status_code, 400)
