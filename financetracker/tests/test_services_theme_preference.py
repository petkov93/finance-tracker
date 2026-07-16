from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

from financetracker.models import UserProfile, ensure_user_profile
from financetracker.services.theme_constants import (
    DEFAULT_THEME_PREFERENCE,
    THEME_COOKIE_NAME,
    THEME_NIGHT,
    THEME_WARM,
)
from financetracker.services.theme_preference import (
    cookie_kwargs,
    for_request,
    preference_for,
    set_preference,
)


class PreferenceForTests(TestCase):
    def test_guest_gets_default_theme_preference(self):
        self.assertEqual(preference_for(None), DEFAULT_THEME_PREFERENCE)

    def test_authenticated_user_reads_profile_theme(self):
        user = User.objects.create_user(username="reader", password="pass1234")
        profile = ensure_user_profile(user)
        profile.theme = THEME_NIGHT
        profile.save(update_fields=["theme"])

        self.assertEqual(preference_for(user), THEME_NIGHT)


class SetPreferenceTests(TestCase):
    def test_persists_valid_theme_preference(self):
        user = User.objects.create_user(username="writer", password="pass1234")

        result = set_preference(user, THEME_WARM)

        self.assertEqual(result, THEME_WARM)
        profile = UserProfile.objects.get(user=user)
        self.assertEqual(profile.theme, THEME_WARM)

    def test_invalid_value_raises_without_changing_profile(self):
        user = User.objects.create_user(username="guard", password="pass1234")
        profile = ensure_user_profile(user)
        profile.theme = THEME_WARM
        profile.save(update_fields=["theme"])

        with self.assertRaises(ValueError):
            set_preference(user, "neon")

        profile.refresh_from_db()
        self.assertEqual(profile.theme, THEME_WARM)


class CookieKwargsTests(TestCase):
    def test_builds_fouc_cookie_settings(self):
        kwargs = cookie_kwargs(THEME_NIGHT)

        self.assertEqual(
            kwargs,
            {
                "key": THEME_COOKIE_NAME,
                "value": THEME_NIGHT,
                "max_age": 60 * 60 * 24 * 365,
                "samesite": "Lax",
                "httponly": False,
            },
        )


class ForRequestTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="memo", password="pass1234")

    def test_guest_request_gets_default_without_profile_lookup(self):
        request = self.factory.get("/login/")

        self.assertEqual(for_request(request), DEFAULT_THEME_PREFERENCE)

    @patch("financetracker.services.theme_preference.ensure_user_profile")
    def test_authenticated_request_resolves_once_per_request(self, mock_ensure):
        mock_ensure.return_value = MagicMock(theme=THEME_WARM)
        request = self.factory.get("/settings/")
        request.user = self.user

        self.assertEqual(for_request(request), THEME_WARM)
        self.assertEqual(for_request(request), THEME_WARM)
        mock_ensure.assert_called_once_with(self.user)
