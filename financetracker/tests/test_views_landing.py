from django.test import Client, TestCase
from django.urls import reverse

from financetracker.tests.factories import DEFAULT_PASSWORD, create_user


class LandingViewsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = create_user()

    def test_guest_get_root_returns_landing(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(reverse("landing"), "/")
        self.assertContains(
            response,
            "Income, spending, investments — finally in one place.",
        )
        self.assertContains(response, "Display conversion")
        self.assertContains(response, "Transaction currency")
        self.assertContains(response, "Default currency")
        self.assertContains(response, reverse("register"))
        self.assertContains(response, reverse("login"))
        self.assertContains(response, 'data-landing-shot="dashboard"')
        self.assertContains(response, 'data-landing-shot="statistics"')
        self.assertContains(response, 'data-landing-shot="converter"')
        self.assertContains(response, "Open your ledger")
        self.assertContains(response, "financetracker/img/landing/dashboard.png")
        self.assertContains(response, "financetracker/img/landing/statistics.png")
        self.assertContains(response, "financetracker/img/landing/converter.png")

    def test_authenticated_root_redirects_to_dashboard(self):
        self.client.login(username=self.user.username, password=DEFAULT_PASSWORD)
        response = self.client.get("/")
        self.assertRedirects(response, reverse("dashboard"))

    def test_dashboard_lives_at_dashboard_path_and_requires_login(self):
        self.assertEqual(reverse("dashboard"), "/dashboard/")
        anonymous = self.client.get(reverse("dashboard"))
        self.assertRedirects(anonymous, f"{reverse('login')}?next=/dashboard/")
        self.client.login(username=self.user.username, password=DEFAULT_PASSWORD)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dashboard")

    def test_guest_brand_links_to_landing(self):
        response = self.client.get(reverse("landing"))
        self.assertContains(response, f'href="{reverse("landing")}"')
        self.assertContains(response, "Finance Tracker")
