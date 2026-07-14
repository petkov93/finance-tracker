from django.contrib.auth.models import User
from django.test import TestCase

from financetracker.models import UserProfile, ensure_user_profile


class UserProfileTests(TestCase):
    def test_ensure_user_profile_creates_czk_default(self):
        user = User.objects.create_user(username="lazy", password="pass1234")

        profile = ensure_user_profile(user)

        self.assertEqual(profile.default_currency, "CZK")
        self.assertEqual(UserProfile.objects.filter(user=user).count(), 1)

    def test_ensure_user_profile_returns_existing_without_overwrite(self):
        user = User.objects.create_user(username="existing", password="pass1234")
        UserProfile.objects.create(user=user, default_currency="EUR")

        profile = ensure_user_profile(user)

        self.assertEqual(profile.default_currency, "EUR")
        self.assertEqual(UserProfile.objects.filter(user=user).count(), 1)
