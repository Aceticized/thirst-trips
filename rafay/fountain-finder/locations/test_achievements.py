import json
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from .achievements import achievement_status
from .models import CheckIn, Facility, UserAchievement, UserProfile
from .services import check_in


class AchievementTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="explorer")
        self.facilities = [Facility.objects.create(
            name=f"Fountain {i}", building="Library", latitude=53.5, longitude=-113.5
        ) for i in range(5)]

    def confirm(self, facility):
        return self.client.post("/api/checkin/", json.dumps({"token": str(facility.nfc_id)}),
                                content_type="application/json")

    def test_first_unlock_and_duplicate_confirmation(self):
        self.client.force_login(self.user)
        response = self.confirm(self.facilities[0])
        self.assertEqual(response.status_code, 201)
        award = response.json()["new_achievements"][0]
        self.assertEqual(award["code"], "first_check_in")
        self.assertTrue(award["unlocked"])
        self.assertIsNotNone(award["unlocked_at"])
        self.assertEqual(self.confirm(self.facilities[0]).json()["new_achievements"], [])
        self.assertEqual(UserAchievement.objects.filter(user=self.user).count(), 1)

    def test_fifth_distinct_fountain_unlocks_two_milestones(self):
        for facility in self.facilities[:4]:
            check_in(self.user, facility)
        before = {a["code"]: a for a in achievement_status(self.user)}
        self.assertEqual(before["points_50"]["progress"], 40)
        self.assertFalse(before["points_50"]["unlocked"])
        visit, _, _ = check_in(self.user, self.facilities[4])
        self.assertEqual({a["code"] for a in visit.new_achievements}, {"points_50", "fountains_5"})
        UserProfile.objects.filter(user=self.user).update(total_points=0)
        self.assertTrue(all(a["unlocked"] for a in achievement_status(self.user)
                            if a["code"] != "new_fountain"))

    def test_staff_balance_does_not_count_as_earned_points(self):
        UserProfile.objects.create(user=self.user, total_points=1000)
        check_in(self.user, self.facilities[0])
        milestone = next(a for a in achievement_status(self.user) if a["code"] == "points_50")
        self.assertEqual(milestone["progress"], 10)
        self.assertFalse(milestone["unlocked"])

    def test_washrooms_do_not_count_as_distinct_fountains(self):
        self.facilities[4].facility_type = Facility.Type.WASHROOM
        self.facilities[4].save()
        for facility in self.facilities:
            check_in(self.user, facility)
        self.assertFalse(UserAchievement.objects.filter(user=self.user, code="fountains_5").exists())
        self.assertTrue(UserAchievement.objects.filter(user=self.user, code="points_50").exists())

    def test_status_is_private_read_only_and_cannot_select_another_user(self):
        self.assertEqual(self.client.get("/api/achievements/").status_code, 401)
        check_in(self.user, self.facilities[0])
        other = get_user_model().objects.create_user(username="other")
        self.client.force_login(other)
        response = self.client.get(f"/api/achievements/?user_id={self.user.pk}")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(all(a["progress"] == 0 and not a["unlocked"]
                            for a in response.json()["achievements"]))
        self.assertEqual(self.client.post("/api/achievements/").status_code, 405)
        self.assertFalse(UserAchievement.objects.filter(user=other).exists())

    def test_achievement_failure_rolls_back_checkin_and_points(self):
        UserProfile.objects.create(user=self.user)
        with patch("locations.services.unlock_achievements", side_effect=RuntimeError("failed")):
            with self.assertRaises(RuntimeError):
                check_in(self.user, self.facilities[0])
        self.assertFalse(CheckIn.objects.filter(user=self.user).exists())
        self.assertEqual(UserProfile.objects.get(user=self.user).total_points, 0)

    def test_database_prevents_duplicate_unlocks(self):
        check_in(self.user, self.facilities[0])
        with self.assertRaises(IntegrityError), transaction.atomic():
            UserAchievement.objects.create(user=self.user, code="first_check_in")

    def test_html_checkin_also_unlocks(self):
        self.client.force_login(self.user)
        response = self.client.post(f"/checkin/{self.facilities[0].nfc_id}/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(UserAchievement.objects.filter(user=self.user, code="first_check_in").exists())

    def test_discovery_credits_session_user_and_awards_once(self):
        data = {"name": "New fountain", "building": "Library", "floor": "2",
                "latitude": 54.0, "longitude": -113.0}
        url = "/api/facilities/discover/"
        def submit(payload):
            return self.client.post(url, json.dumps(payload), content_type="application/json")
        self.assertEqual(submit(data).status_code, 401)
        self.client.force_login(self.user)
        self.assertEqual(submit({**data, "discovered_by": 999}).status_code, 400)
        response = submit(data)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["new_achievements"][0]["code"], "new_fountain")
        self.assertEqual(Facility.objects.get(pk=response.json()["id"]).discovered_by, self.user)
        self.assertEqual(submit(data).status_code, 409)
        self.assertEqual(submit({**data, "latitude": 54.1}).json()["new_achievements"], [])

    def test_notification_claim_is_per_user_and_never_repeats(self):
        check_in(self.user, self.facilities[0])
        url = "/api/achievements/notifications/claim/"
        self.assertEqual(self.client.post(url, "{}", content_type="application/json").status_code, 401)
        other = get_user_model().objects.create_user(username="other")
        self.client.force_login(other)
        self.assertEqual(self.client.post(url, "{}", content_type="application/json").json()["notifications"], [])
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(url).status_code, 405)
        first = self.client.post(url, "{}", content_type="application/json").json()
        self.assertEqual(first["notifications"][0]["code"], "first_check_in")
        self.assertEqual(self.client.post(url, "{}", content_type="application/json").json()["notifications"], [])
        self.assertIsNotNone(UserAchievement.objects.get(user=self.user).notification_seen_at)


class AchievementPopupArtTests(TestCase):
    STATIC = Path(__file__).resolve().parent / "static" / "locations" / "achievements"

    def test_every_achievement_has_its_popup_picture_and_the_sound_exists(self):
        from .achievements import ACHIEVEMENTS
        for item in ACHIEVEMENTS:
            self.assertTrue((self.STATIC / f"{item['code']}.png").exists(), f"no picture for {item['code']}")
        self.assertTrue((self.STATIC / "unlock.mp3").exists())

    def test_check_in_page_lets_the_popup_take_over_the_sound(self):
        user = get_user_model().objects.create_user(username="walker", password="Fountain!River728")
        facility = Facility.objects.create(name="f1", building="CAB", latitude=53.5, longitude=-113.5)
        self.client.force_login(user)
        response = self.client.get(f"/checkin/{facility.nfc_id}/")
        self.assertContains(response, 'dispatchEvent(new Event("achievements:check"))')
        self.assertContains(response, '"achievements:popup"')
