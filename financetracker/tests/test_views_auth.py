from django.test import Client, TestCase
from django.urls import reverse

from financetracker.tests.factories import DEFAULT_PASSWORD, create_user


class AuthViewsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = create_user()

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

    def test_register_creates_user_and_logs_in(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "newuser",
                "password1": "ComplexPass123!",
                "password2": "ComplexPass123!",
            },
        )
        self.assertRedirects(response, reverse("dashboard"))
        self.assertTrue(self.client.session.get("_auth_user_id"))

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
