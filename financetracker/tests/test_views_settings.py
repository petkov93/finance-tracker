from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from financetracker.models import InvestmentEntry, Transaction
from financetracker.tests.factories import (
    DEFAULT_PASSWORD,
    create_investment,
    create_transaction,
    create_user,
)


class SettingsViewsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = create_user(username="alice", email="alice@example.com")
        self.other_user = create_user(username="bob")
        self.client.login(username=self.user.username, password=DEFAULT_PASSWORD)

    def test_settings_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("settings"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('settings')}")

    def test_profile_update(self):
        response = self.client.post(
            reverse("settings"),
            {
                "action": "profile",
                "username": "alice2",
                "email": "alice2@example.com",
            },
        )
        self.assertRedirects(response, reverse("settings"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "alice2")
        self.assertEqual(self.user.email, "alice2@example.com")

    def test_password_change_keeps_session(self):
        response = self.client.post(
            reverse("settings"),
            {
                "action": "password",
                "old_password": DEFAULT_PASSWORD,
                "new_password1": "NewComplexPass456!",
                "new_password2": "NewComplexPass456!",
            },
        )
        self.assertRedirects(response, reverse("settings"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewComplexPass456!"))
        self.assertEqual(str(self.user.pk), self.client.session.get("_auth_user_id"))

    def test_clear_all_transactions_only_for_current_user(self):
        create_transaction(self.user)
        create_transaction(self.user)
        create_transaction(self.other_user)

        response = self.client.post(reverse("clear_all_transactions"))
        self.assertRedirects(response, reverse("settings"))
        self.assertEqual(Transaction.objects.filter(user=self.user).count(), 0)
        self.assertEqual(Transaction.objects.filter(user=self.other_user).count(), 1)

    def test_clear_all_investments_only_for_current_user(self):
        create_investment(self.user, amount=Decimal("100.00"))
        create_investment(self.other_user, amount=Decimal("200.00"))

        response = self.client.post(reverse("clear_all_investments"))
        self.assertRedirects(response, reverse("settings"))
        self.assertEqual(InvestmentEntry.objects.filter(user=self.user).count(), 0)
        self.assertEqual(InvestmentEntry.objects.filter(user=self.other_user).count(), 1)

    def test_settings_shows_counts(self):
        create_transaction(self.user)
        create_investment(self.user)
        response = self.client.get(reverse("settings"))
        self.assertEqual(response.context["transaction_count"], 1)
        self.assertEqual(response.context["investment_count"], 1)
