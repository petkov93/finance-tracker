import importlib

from django.apps import apps
from django.contrib.auth.models import User
from django.test import TestCase

from financetracker.models import UserProfile

backfill_user_profiles = importlib.import_module(
    "financetracker.migrations.0004_userprofile"
).backfill_user_profiles


class UserProfileMigrationTests(TestCase):
    def test_backfill_creates_czk_profile_for_existing_users(self):
        user = User.objects.create_user(username="legacy", password="pass1234")
        UserProfile.objects.all().delete()

        backfill_user_profiles(apps, None)

        profile = UserProfile.objects.get(user=user)
        self.assertEqual(profile.default_currency, "CZK")
