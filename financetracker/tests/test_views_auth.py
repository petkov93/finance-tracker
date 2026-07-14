from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from financetracker.models import UserProfile
from financetracker.tests.factories import DEFAULT_PASSWORD, create_user

SUPPORTED = {"CZK": "Czech Koruna", "EUR": "Euro", "USD": "US Dollar"}


class AuthViewsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = create_user()
        self.supported_patcher = patch(
            "financetracker.views.get_supported_currencies",
            return_value=SUPPORTED.copy(),
        )
        self.supported_patcher.start()
        self.addCleanup(self.supported_patcher.stop)

    def test_dashboard_redirects_anonymous_user(self):
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(response, f"{reverse('login')}?next=/")

    def test_login_success(self):
        response = self.client.post(
            reverse("login"),
            {"username": self.user.username, "password": DEFAULT_PASSWORD},
        )
        self.assertRedirects(response, reverse("dashboard"))

    def test_login_invalid_credentials(self):
        response = self.client.post(
            reverse("login"),
            {"username": self.user.username, "password": "wrong-password"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid username or password.")

    def test_login_creates_profile_for_user_without_one(self):
        UserProfile.objects.filter(user=self.user).delete()
        response = self.client.post(
            reverse("login"),
            {"username": self.user.username, "password": DEFAULT_PASSWORD},
        )
        self.assertRedirects(response, reverse("dashboard"))
        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.default_currency, "CZK")

    def test_register_creates_user_profile_and_logs_in(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "newuser",
                "password1": "ComplexPass123!",
                "password2": "ComplexPass123!",
                "default_currency": "EUR",
            },
        )
        self.assertRedirects(response, reverse("dashboard"))
        self.assertTrue(self.client.session.get("_auth_user_id"))
        user = User.objects.get(username="newuser")
        profile = UserProfile.objects.get(user=user)
        self.assertEqual(profile.default_currency, "EUR")

    def test_register_requires_default_currency(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "newuser",
                "password1": "ComplexPass123!",
                "password2": "ComplexPass123!",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="newuser").exists())

    def test_register_rejects_unsupported_currency(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "newuser",
                "password1": "ComplexPass123!",
                "password2": "ComplexPass123!",
                "default_currency": "XYZ",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="newuser").exists())

    def test_register_page_includes_locale_currency_script(self):
        response = self.client.get(reverse("register"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="id_default_currency"')
        self.assertContains(response, "register.js")

    def test_authenticated_user_redirected_from_login(self):
        self.client.login(username=self.user.username, password=DEFAULT_PASSWORD)
        response = self.client.get(reverse("login"))
        self.assertRedirects(response, reverse("dashboard"))

    def test_logout_requires_post(self):
        self.client.login(username=self.user.username, password=DEFAULT_PASSWORD)
        response = self.client.get(reverse("logout"))
        self.assertEqual(response.status_code, 405)

    def test_logout_success(self):
        self.client.login(username=self.user.username, password=DEFAULT_PASSWORD)
        response = self.client.post(reverse("logout"))
        self.assertRedirects(response, reverse("login"))
