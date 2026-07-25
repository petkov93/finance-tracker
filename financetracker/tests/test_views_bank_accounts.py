from decimal import Decimal
from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse

from financetracker.models import BankAccount, Transaction, ensure_user_profile
from financetracker.services.bank_accounts import (
    bank_account_balance,
    create_bank_account,
    ensure_cash_bank_account,
)
from financetracker.tests.factories import (
    DEFAULT_PASSWORD,
    create_transaction,
    create_user,
)

SUPPORTED = {"CZK": "Czech Koruna", "EUR": "Euro", "USD": "US Dollar"}


class BankAccountViewsTestCase(TestCase):
    def setUp(self):
        self.user = create_user()
        ensure_user_profile(self.user)
        self.cash = ensure_cash_bank_account(self.user)
        self.client = Client()
        self.client.login(username=self.user.username, password=DEFAULT_PASSWORD)
        self.supported_patcher = patch(
            "financetracker.views.get_supported_currencies",
            return_value=SUPPORTED.copy(),
        )
        self.supported_patcher.start()
        self.addCleanup(self.supported_patcher.stop)


class BankAccountListViewsTests(BankAccountViewsTestCase):
    def test_list_shows_bank_accounts_with_balances(self):
        account = create_bank_account(
            self.user,
            name="ČSOB savings",
            currency="CZK",
            kind=BankAccount.SAVINGS,
            opening_balance=Decimal("1500.00"),
        )

        response = self.client.get(reverse("bank_accounts"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cash")
        self.assertContains(response, "ČSOB savings")
        self.assertContains(response, "1")
        accounts = {row["account"].pk: row for row in response.context["account_rows"]}
        self.assertEqual(accounts[account.pk]["balance"], Decimal("1500.00"))
        self.assertEqual(
            accounts[self.cash.pk]["balance"],
            bank_account_balance(self.cash),
        )


class BankAccountCreateViewsTests(BankAccountViewsTestCase):
    def test_create_bank_account_via_form(self):
        response = self.client.post(
            reverse("add_bank_account"),
            {
                "name": "Revolut",
                "currency": "EUR",
                "kind": BankAccount.CHECKING,
                "opening_balance": "250.00",
            },
        )

        self.assertEqual(response.status_code, 302)
        account = BankAccount.objects.get(user=self.user, name="Revolut")
        self.assertEqual(account.currency, "EUR")
        self.assertEqual(account.kind, BankAccount.CHECKING)
        self.assertEqual(bank_account_balance(account), Decimal("250.00"))


class BankAccountRenameViewsTests(BankAccountViewsTestCase):
    def test_rename_custom_bank_account_via_form(self):
        account = create_bank_account(
            self.user,
            name="Old name",
            currency="CZK",
        )

        response = self.client.post(
            reverse("edit_bank_account", args=[account.pk]),
            {"name": "New name"},
        )

        self.assertEqual(response.status_code, 302)
        account.refresh_from_db()
        self.assertEqual(account.name, "New name")
        self.assertEqual(account.currency, "CZK")

    def test_edit_form_does_not_allow_currency_change(self):
        account = create_bank_account(
            self.user,
            name="Locked",
            currency="CZK",
        )

        response = self.client.get(reverse("edit_bank_account", args=[account.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("currency", response.context["form"].fields)


class BankAccountDeleteViewsTests(BankAccountViewsTestCase):
    def test_delete_empty_custom_bank_account(self):
        account = create_bank_account(
            self.user,
            name="Empty",
            currency="CZK",
            opening_balance=Decimal("0"),
        )

        response = self.client.post(reverse("delete_bank_account", args=[account.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(BankAccount.objects.filter(pk=account.pk).exists())

    def test_delete_cash_is_blocked(self):
        response = self.client.post(reverse("delete_bank_account", args=[self.cash.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(BankAccount.objects.filter(pk=self.cash.pk).exists())

    def test_delete_with_opening_balance_is_blocked(self):
        account = create_bank_account(
            self.user,
            name="With opening",
            currency="CZK",
            opening_balance=Decimal("50.00"),
        )

        response = self.client.post(reverse("delete_bank_account", args=[account.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(BankAccount.objects.filter(pk=account.pk).exists())


class OpeningBalanceSpendingViewTests(BankAccountViewsTestCase):
    def test_dashboard_spending_excludes_opening_balance_but_available_includes_it(self):
        create_bank_account(
            self.user,
            name="Savings",
            currency="CZK",
            opening_balance=Decimal("1000.00"),
        )
        create_transaction(
            self.user,
            amount=Decimal("100.00"),
            currency="CZK",
            type=Transaction.INCOME,
            bank_account=self.cash,
        )
        create_transaction(
            self.user,
            amount=Decimal("40.00"),
            currency="CZK",
            type=Transaction.EXPENSE,
            bank_account=self.cash,
        )

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.context["total_income"], Decimal("100.00"))
        self.assertEqual(response.context["total_expense"], Decimal("40.00"))
        self.assertEqual(response.context["available"], Decimal("1060.00"))

    def test_statistics_excludes_opening_balance(self):
        create_bank_account(
            self.user,
            name="Savings",
            currency="CZK",
            opening_balance=Decimal("1000.00"),
        )
        create_transaction(
            self.user,
            amount=Decimal("100.00"),
            currency="CZK",
            type=Transaction.INCOME,
            bank_account=self.cash,
        )

        response = self.client.get(reverse("statistics"))

        self.assertEqual(response.context["total_income"], 100.0)
