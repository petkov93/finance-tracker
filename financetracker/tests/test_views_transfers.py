from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.messages import get_messages
from django.test import Client, TestCase
from django.urls import reverse

from financetracker.models import Transaction, Transfer, ensure_user_profile
from financetracker.services.bank_accounts import (
    bank_account_balance,
    create_bank_account,
    create_transfer,
    ensure_cash_bank_account,
)
from financetracker.tests.factories import (
    DEFAULT_PASSWORD,
    create_transaction,
    create_user,
)

SUPPORTED = {"CZK": "Czech Koruna", "EUR": "Euro", "USD": "US Dollar"}


class TransferViewsTestCase(TestCase):
    def setUp(self):
        self.user = create_user()
        ensure_user_profile(self.user)
        self.cash = ensure_cash_bank_account(self.user)
        self.savings = create_bank_account(
            self.user,
            name="Savings",
            currency="CZK",
        )
        create_transaction(
            self.user,
            amount=Decimal("1000.00"),
            currency="CZK",
            type=Transaction.INCOME,
            bank_account=self.cash,
        )
        self.client = Client()
        self.client.login(username=self.user.username, password=DEFAULT_PASSWORD)
        self.supported_patcher = patch(
            "financetracker.views.get_supported_currencies",
            return_value=SUPPORTED.copy(),
        )
        self.supported_patcher.start()
        self.addCleanup(self.supported_patcher.stop)


class TransferCreateViewsTests(TransferViewsTestCase):
    def test_create_transfer_via_form(self):
        response = self.client.post(
            reverse("add_transfer"),
            {
                "from_bank_account": self.cash.pk,
                "to_bank_account": self.savings.pk,
                "amount": "250.00",
                "date": "2026-07-01",
            },
        )

        self.assertEqual(response.status_code, 302)
        transfer = Transfer.objects.get(user=self.user)
        self.assertEqual(transfer.from_bank_account, self.cash)
        self.assertEqual(transfer.to_bank_account, self.savings)
        self.assertEqual(transfer.source_transaction.amount, Decimal("250.00"))
        self.assertEqual(bank_account_balance(self.cash), Decimal("750.00"))
        self.assertEqual(bank_account_balance(self.savings), Decimal("250.00"))

    def test_create_transfer_rejects_same_account(self):
        response = self.client.post(
            reverse("add_transfer"),
            {
                "from_bank_account": self.cash.pk,
                "to_bank_account": self.cash.pk,
                "amount": "50.00",
                "date": "2026-07-01",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Transfer.objects.count(), 0)
        self.assertTrue(response.context["form"].errors)


class TransferEditDeleteViewsTests(TransferViewsTestCase):
    def setUp(self):
        super().setUp()
        self.transfer = create_transfer(
            self.user,
            from_bank_account=self.cash,
            to_bank_account=self.savings,
            amount=Decimal("200.00"),
            transfer_date=date(2026, 7, 1),
        )

    def test_edit_transfer_via_form(self):
        checking = create_bank_account(
            self.user,
            name="Checking",
            currency="CZK",
        )

        response = self.client.post(
            reverse("edit_transfer", args=[self.transfer.pk]),
            {
                "from_bank_account": self.cash.pk,
                "to_bank_account": checking.pk,
                "amount": "125.00",
                "date": "2026-07-10",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.transfer.refresh_from_db()
        self.assertEqual(self.transfer.to_bank_account, checking)
        self.assertEqual(self.transfer.source_transaction.amount, Decimal("125.00"))
        self.assertEqual(bank_account_balance(self.savings), Decimal("0"))
        self.assertEqual(bank_account_balance(checking), Decimal("125.00"))

    def test_delete_transfer_via_post(self):
        response = self.client.post(
            reverse("delete_transfer", args=[self.transfer.pk]),
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Transfer.objects.filter(pk=self.transfer.pk).exists())
        self.assertEqual(bank_account_balance(self.cash), Decimal("1000.00"))

    def test_dashboard_blocks_editing_transfer_leg(self):
        response = self.client.get(
            reverse("edit_transaction", args=[self.transfer.source_transaction_id]),
        )

        self.assertEqual(response.status_code, 302)
        messages = [m.message for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("Transfer" in msg for msg in messages))


class TransferListAndSpendingViewsTests(TransferViewsTestCase):
    def test_bank_accounts_page_lists_transfers(self):
        create_transfer(
            self.user,
            from_bank_account=self.cash,
            to_bank_account=self.savings,
            amount=Decimal("80.00"),
            transfer_date=date(2026, 7, 1),
        )

        response = self.client.get(reverse("bank_accounts"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Transfer")
        self.assertEqual(len(response.context["transfers"]), 1)

    def test_dashboard_spending_pills_exclude_transfer_amounts(self):
        create_transaction(
            self.user,
            amount=Decimal("40.00"),
            currency="CZK",
            type=Transaction.EXPENSE,
            bank_account=self.cash,
        )
        create_transfer(
            self.user,
            from_bank_account=self.cash,
            to_bank_account=self.savings,
            amount=Decimal("100.00"),
            transfer_date=date(2026, 7, 1),
        )

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_expense"], Decimal("40.00"))
