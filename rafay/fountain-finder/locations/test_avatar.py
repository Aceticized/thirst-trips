from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase

from . import avatar
from .models import UserProfile

PASSWORD = "Fountain!River728"
STATIC_DIR = Path(__file__).resolve().parent / "static"


def make_player(name, points=0, **worn):
    user = get_user_model().objects.create_user(username=name, password=PASSWORD)
    profile = UserProfile.objects.create(user=user, total_points=points, **worn)
    return user, profile


class CatalogTests(TestCase):
    def test_every_accessory_has_its_picture(self):
        for item in avatar.ITEMS:
            self.assertTrue((STATIC_DIR / item.file).exists(), item.file)
        for name in ("base", "edit-avatar", "tab-clothing", "tab-eyes", "tab-mouth"):
            self.assertTrue((STATIC_DIR / "locations" / "avatar" / f"{name}.png").exists(), name)

    def test_the_defaults_are_free_and_every_slot_has_something_free_to_wear(self):
        for slot, key in avatar.DEFAULTS.items():
            if key:
                self.assertEqual(avatar.find_item(slot, key).points, 0)
        for slot in ("eyes", "mouth"):
            self.assertTrue(any(i.points == 0 for i in avatar.ITEMS if i.slot == slot))

    def test_every_wardrobe_tab_has_free_choices_to_start_with(self):
        free = lambda slots: [i for i in avatar.ITEMS if i.slot in slots and i.points == 0]
        self.assertGreaterEqual(len(free(("eyes",))), 2)
        self.assertGreaterEqual(len(free(("mouth",))), 2)
        self.assertGreaterEqual(len(free(("top",))), 1)

    def test_some_accessories_are_locked_at_zero_points(self):
        locked = [i for i in avatar.ITEMS if not avatar.is_unlocked(i, 0)]
        self.assertGreaterEqual(len(locked), 5)
        self.assertEqual(avatar.next_unlock(0).points, min(i.points for i in locked))
        self.assertIsNone(avatar.next_unlock(10_000))

    def test_keys_are_unique_inside_a_slot(self):
        pairs = [(i.slot, i.key) for i in avatar.ITEMS]
        self.assertEqual(len(pairs), len(set(pairs)))

    def test_whole_view_and_zoomed_view(self):
        box, stage = avatar.view_styles(None)
        self.assertEqual(box, "aspect-ratio:1779/1331")
        self.assertIn("width:100%", stage)
        # a window of 1000 original pixels centred in the picture shows it 1.779 times wider than the box
        cx = (avatar.AVATAR_CROP[0] + avatar.AVATAR_CROP[2]) / 2
        cy = (avatar.AVATAR_CROP[1] + avatar.AVATAR_CROP[3]) / 2
        box, stage = avatar.view_styles((cx, cy, 1000))
        self.assertEqual(box, "aspect-ratio:1/1")
        self.assertIn("width:177.900%", stage)
        self.assertIn("left:-38.950%", stage)


class WearingRulesTests(TestCase):
    def test_new_players_wear_the_defaults(self):
        _, profile = make_player("new")
        self.assertEqual(avatar.equipped_for(profile), {"top": "", "eyes": "white", "mouth": "happy", "hat": ""})

    def test_locked_or_unknown_things_are_not_worn(self):
        _, profile = make_player("cheater", 10, avatar_top="drippy", avatar_eyes="wise", avatar_mouth="nonsense", avatar_hat="bow")
        self.assertEqual(avatar.equipped_for(profile), {"top": "", "eyes": "", "mouth": "", "hat": ""})

    def test_items_are_worn_once_the_points_are_there(self):
        _, profile = make_player("rich", 1000, avatar_top="drippy", avatar_eyes="wise", avatar_mouth="tongue", avatar_hat="bow")
        self.assertEqual(avatar.equipped_for(profile), {"top": "drippy", "eyes": "wise", "mouth": "tongue", "hat": "bow"})

    def test_the_exact_threshold_unlocks(self):
        item = avatar.find_item("top", "h2o")
        self.assertFalse(avatar.is_unlocked(item, item.points - 1))
        self.assertTrue(avatar.is_unlocked(item, item.points))


class AvatarPageTests(TestCase):
    def setUp(self):
        self.user, self.profile = make_player("ricky", 55)
        self.client.force_login(self.user)

    def worn(self):
        self.profile.refresh_from_db()
        return avatar.equipped_for(self.profile)

    def test_requires_login(self):
        self.client.logout()
        self.assertRedirects(self.client.get("/avatar/"), "/login/?next=/avatar/")
        self.assertRedirects(self.client.post("/avatar/", {"hat": "bow"}), "/login/?next=/avatar/")

    def test_shows_the_wardrobe_with_locks_and_the_next_unlock(self):
        response = self.client.get("/avatar/")
        self.assertContains(response, "You have <strong>55</strong> points")
        self.assertContains(response, "Next unlock: <strong>Sad eyes</strong> at 60 points")
        self.assertContains(response, "H2O tank top")
        self.assertContains(response, "200 points")
        self.assertContains(response, "locations/avatar/tab-eyes.png")
        tiles = [entry for tab in response.context["tabs"] for group in tab["groups"] for entry in group["items"]]
        by_name = {t["name"]: t for t in tiles}
        self.assertTrue(by_name["H2O tank top"]["unlocked"])
        self.assertFalse(by_name["Pizza tee"]["unlocked"])
        self.assertEqual(len(tiles), len(avatar.ITEMS))

    def test_saving_wears_the_chosen_unlocked_items(self):
        response = self.client.post("/avatar/", {"top": "h2o", "eyes": "square", "mouth": "coy", "hat": "bow"})
        self.assertRedirects(response, "/account/")
        self.assertEqual(self.worn(), {"top": "h2o", "eyes": "square", "mouth": "coy", "hat": "bow"})

    def test_an_empty_choice_takes_the_item_off(self):
        self.client.post("/avatar/", {"top": "h2o", "hat": "bow"})
        self.client.post("/avatar/", {"top": "", "hat": ""})
        self.assertEqual(self.worn()["top"], "")
        self.assertEqual(self.worn()["hat"], "")
        self.assertEqual(self.worn()["eyes"], "white")   # not mentioned, so unchanged

    def test_a_locked_item_is_refused_and_nothing_is_saved(self):
        response = self.client.post("/avatar/", {"top": "h2o", "eyes": "wise"})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Wise eyes unlocks at 150 points.", status_code=400)
        self.assertEqual(self.worn()["top"], "")          # even the allowed item in the same request is not saved
        self.assertEqual(self.worn()["eyes"], "white")

    def test_an_item_in_the_wrong_slot_or_unknown_is_refused(self):
        self.assertEqual(self.client.post("/avatar/", {"hat": "h2o"}).status_code, 400)
        self.assertEqual(self.client.post("/avatar/", {"eyes": "../../etc"}).status_code, 400)
        self.assertEqual(self.worn()["hat"], "")

    def test_you_can_only_change_your_own_raccoon(self):
        other_user, other = make_player("other", 500, avatar_top="pizza")
        self.client.post("/avatar/", {"top": "h2o", "user": other_user.id, "username": "other"})
        other.refresh_from_db()
        self.assertEqual(other.avatar_top, "pizza")

    def test_a_player_without_a_profile_row_gets_one(self):
        loner = get_user_model().objects.create_user(username="loner", password=PASSWORD)
        self.client.force_login(loner)
        self.assertEqual(self.client.get("/avatar/").status_code, 200)
        self.assertTrue(UserProfile.objects.filter(user=loner).exists())


class AccountAndLeaderboardAvatarTests(TestCase):
    def test_account_page_shows_your_raccoon_and_links_to_the_wardrobe(self):
        user, _ = make_player("ricky", 55, avatar_top="h2o")
        self.client.force_login(user)
        response = self.client.get("/account/")
        self.assertContains(response, 'href="/avatar/"')
        self.assertContains(response, "locations/avatar/base.png")
        self.assertContains(response, "locations/avatar/top-h2o.png")
        self.assertContains(response, "locations/avatar/edit-avatar.png")
        self.assertNotContains(response, "top-pizza.png")

    def test_leaderboard_shows_each_players_raccoon_instead_of_a_rank_number(self):
        make_player("gold", 300, avatar_top="drippy")
        make_player("silver", 120, avatar_top="pizza")
        viewer, _ = make_player("viewer", 60, avatar_top="h2o")
        self.client.force_login(viewer)
        response = self.client.get("/leaderboard/")
        for outfit in ("top-drippy.png", "top-pizza.png", "top-h2o.png"):
            self.assertContains(response, outfit)
        self.assertContains(response, 'class="face r1"')
        self.assertContains(response, 'class="face r2"')
        self.assertContains(response, 'class="face r3"')
        self.assertNotContains(response, 'class="rank')
        self.assertContains(response, "Rank 1: ")                  # still announced to screen readers
        self.assertEqual([r["avatar"]["top"] for r in response.context["rows"]], ["drippy", "pizza", "h2o"])

    def test_leaderboard_never_shows_an_item_the_player_has_not_unlocked(self):
        make_player("faker", 5, avatar_top="drippy", avatar_eyes="wise")
        viewer, _ = make_player("viewer", 5)
        self.client.force_login(viewer)
        response = self.client.get("/leaderboard/")
        self.assertNotContains(response, "top-drippy.png")
        self.assertNotContains(response, "eyes-wise.png")

    def test_your_rank_number_is_kept_when_you_are_listed_below_the_board(self):
        from unittest import mock
        from . import views
        viewer, _ = make_player("viewer", 5, avatar_hat="bow")
        for index in range(3):
            make_player(f"leader{index}", 100 - index)
        self.client.force_login(viewer)
        with mock.patch.object(views, "LEADERBOARD_SIZE", 2):
            response = self.client.get("/leaderboard/")
        self.assertContains(response, '<span class="place">#4</span>', html=True)
        self.assertEqual(response.context["my_row"]["avatar"]["eyes"], "white")
