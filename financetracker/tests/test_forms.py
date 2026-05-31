from django.test import TestCase

from financetracker.forms import ProfileForm
from financetracker.tests.factories import create_user


class ProfileFormTests(TestCase):
    def test_rejects_duplicate_username(self):
        create_user(username="taken")
        other = create_user(username="other")
        form = ProfileForm(
            data={"username": "taken", "email": "other@example.com"},
            instance=other,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("username", form.errors)

    def test_allows_keeping_own_username(self):
        user = create_user(username="alice", email="alice@example.com")
        form = ProfileForm(
            data={"username": "alice", "email": "alice@example.com"},
            instance=user,
        )
        self.assertTrue(form.is_valid())

    def test_saves_updated_email(self):
        user = create_user(username="alice")
        form = ProfileForm(
            data={"username": "alice", "email": "new@example.com"},
            instance=user,
        )
        self.assertTrue(form.is_valid())
        saved = form.save()
        self.assertEqual(saved.email, "new@example.com")
