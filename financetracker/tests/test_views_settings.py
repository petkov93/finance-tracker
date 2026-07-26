from decimal import Decimal
from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse

from financetracker.models import InvestmentEntry, Transaction, UserProfile, ensure_user_profile
from financetracker.services.iou import create_receivable, record_repayment
from financetracker.tests.factories import (
    DEFAULT_PASSWORD,
    create_investment,
    create_transaction,
    create_user,
)

SUPPORTED = {"CZK": "Czech Koruna", "EUR": "Euro", "USD": "US Dollar"}


class SettingsViewsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = create_user(username="alice", email="alice@example.com")
        self.other_user = create_user(username="bob")
        self.client.login(username=self.user.username, password=DEFAULT_PASSWORD)
        self.supported_patcher = patch(
            "financetracker.views.get_supported_currencies",
            return_value=SUPPORTED.copy(),
        )
        self.supported_patcher.start()
        self.addCleanup(self.supported_patcher.stop)
        ensure_user_profile(self.user)
        ensure_user_profile(self.other_user)

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

    def test_clear_all_transactions_skips_iou_linked(self):
        plain = create_transaction(self.user, amount=Decimal("40.00"))
        iou = create_receivable(
            self.user,
            counterparty_name="Pat",
            amount=Decimal("100.00"),
            currency="CZK",
        )
        record_repayment(iou, amount=Decimal("25.00"))
        repayment_tx = iou.repayments.get().transaction
        opening_id = iou.opening_transaction_id

        response = self.client.post(reverse("clear_all_transactions"))
        self.assertRedirects(response, reverse("settings"))
        self.assertFalse(Transaction.objects.filter(pk=plain.pk).exists())
        self.assertTrue(Transaction.objects.filter(pk=opening_id).exists())
        self.assertTrue(Transaction.objects.filter(pk=repayment_tx.pk).exists())
        self.assertEqual(Transaction.objects.filter(user=self.user).count(), 2)

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
        create_receivable(
            self.user,
            counterparty_name="Pat",
            amount=Decimal("50.00"),
            currency="CZK",
        )
        response = self.client.get(reverse("settings"))
        self.assertEqual(response.context["transaction_count"], 1)
        self.assertEqual(response.context["investment_count"], 1)

    def test_settings_currency_dropdown_lists_supported_currencies(self):
        response = self.client.get(reverse("settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<option value="CZK"')
        self.assertContains(response, '<option value="EUR"')
        self.assertContains(response, '<option value="USD"')
        self.assertContains(response, '<optgroup label="Common currencies">')
        self.assertContains(response, '<optgroup label="All currencies">')

    def test_default_currency_update(self):
        response = self.client.post(
            reverse("settings"),
            {
                "action": "currency",
                "default_currency": "USD",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.default_currency, "USD")
        self.assertContains(response, "Default currency updated.")

    def test_settings_lazy_creates_profile_for_user_without_one(self):
        UserProfile.objects.filter(user=self.user).delete()
        response = self.client.get(reverse("settings"))
        self.assertEqual(response.status_code, 200)
        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.default_currency, "CZK")
        self.assertEqual(profile.theme, "system")

    def test_theme_update_persists_and_shows_selection(self):
        for theme in ("warm", "night", "cool", "system"):
            with self.subTest(theme=theme):
                response = self.client.post(
                    reverse("settings"),
                    {
                        "action": "theme",
                        "theme": theme,
                    },
                    follow=True,
                )
                self.assertEqual(response.status_code, 200)
                profile = UserProfile.objects.get(user=self.user)
                self.assertEqual(profile.theme, theme)
                self.assertContains(response, "Appearance updated.")
                self.assertEqual(response.context["selected_theme"], theme)
                self.assertContains(
                    response,
                    f'class="theme-swatch theme-swatch-{theme} is-selected"',
                )
                self.assertContains(response, 'aria-pressed="true"')

    def test_theme_update_sets_preference_cookie(self):
        for theme in ("night", "cool"):
            with self.subTest(theme=theme):
                response = self.client.post(
                    reverse("settings"),
                    {
                        "action": "theme",
                        "theme": theme,
                    },
                )
                self.assertRedirects(response, reverse("settings"))
                self.assertEqual(response.cookies["ft_theme"].value, theme)

    def test_invalid_theme_does_not_change_preference(self):
        profile = UserProfile.objects.get(user=self.user)
        profile.theme = "warm"
        profile.save(update_fields=["theme"])

        response = self.client.post(
            reverse("settings"),
            {
                "action": "theme",
                "theme": "neon",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        profile.refresh_from_db()
        self.assertEqual(profile.theme, "warm")
        self.assertContains(response, "Invalid appearance choice.")

    def test_theme_update_requires_login(self):
        self.client.logout()
        response = self.client.post(
            reverse("settings"),
            {
                "action": "theme",
                "theme": "night",
            },
        )
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('settings')}")

    def test_guest_login_page_loads_without_theme_preference(self):
        self.client.logout()
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
