from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from financetracker.admin import BankAccountAdmin
from financetracker.models import BankAccount, Transaction
from financetracker.services.bank_accounts import (
    assign_transactions_to_bank_account,
    BankAccountError,
    ensure_cash_bank_account,
)
from financetracker.tests.factories import (
    create_bank_account,
    create_category,
    create_transaction,
    create_user,
    DEFAULT_PASSWORD,
)


class BankAccountAdminTests(TestCase):
    def setUp(self):
        self.site = AdminSite()
        self.admin = BankAccountAdmin(BankAccount, self.site)
        self.factory = RequestFactory()
        self.user = create_user(username="adminuser")
        self.request = self.factory.get("/admin/")
        self.request.user = self.user

    def test_cash_has_no_delete_permission(self):
        cash = ensure_cash_bank_account(self.user)

        self.assertFalse(self.admin.has_delete_permission(self.request, cash))

    def test_non_cash_keeps_default_delete_permission(self):
        ensure_cash_bank_account(self.user)
        savings = BankAccount.objects.create(
            user=self.user,
            name="Savings",
            currency="CZK",
            kind=BankAccount.SAVINGS,
            is_cash=False,
        )
        staff = User.objects.create_superuser(
            username="staff",
            email="staff@example.com",
            password="pass1234",
        )
        self.request.user = staff

        self.assertTrue(self.admin.has_delete_permission(self.request, savings))


class BulkAssignTransactionsAdminTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.staff = User.objects.create_superuser(
            username="staff",
            email="staff@example.com",
            password=DEFAULT_PASSWORD,
        )
        self.client.login(username="staff", password=DEFAULT_PASSWORD)
        self.user = create_user(username="owner")
        self.category = create_category()
        self.cash = ensure_cash_bank_account(self.user)
        self.euro_account = create_bank_account(
            self.user,
            name="Euro pot",
            currency="EUR",
            kind=BankAccount.SAVINGS,
        )
        self.changelist_url = reverse("admin:financetracker_transaction_changelist")

    def _post_action(self, transactions, extra=None):
        data = {
            "action": "assign_transactions_to_bank_account",
            "_selected_action": [tx.pk for tx in transactions],
        }
        if extra:
            data.update(extra)
        return self.client.post(self.changelist_url, data)

    def test_bulk_assign_happy_path(self):
        transaction = create_transaction(
            self.user,
            amount="25.00",
            currency="EUR",
            category=self.category,
            bank_account=self.cash,
        )
        Transaction.objects.filter(pk=transaction.pk).update(currency="EUR")
        transaction.refresh_from_db()
        self.assertEqual(transaction.bank_account_id, self.cash.id)

        response = self._post_action([transaction])
        self.assertEqual(response.status_code, 200)
        self.assertIn("form", response.context)

        response = self._post_action(
            [transaction],
            extra={
                "apply": "Assign",
                "bank_account": self.euro_account.pk,
            },
        )
        self.assertRedirects(response, self.changelist_url)
        transaction.refresh_from_db()
        self.assertEqual(transaction.bank_account_id, self.euro_account.id)

    def test_bulk_assign_form_excludes_bank_accounts_from_other_users(self):
        other_user = create_user(username="other")
        other_cash = ensure_cash_bank_account(other_user)
        transaction = create_transaction(
            self.user,
            amount="25.00",
            currency="EUR",
            category=self.category,
            bank_account=self.cash,
        )
        Transaction.objects.filter(pk=transaction.pk).update(currency="EUR")

        response = self._post_action(
            [transaction],
            extra={
                "apply": "Assign",
                "bank_account": other_cash.pk,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("form", response.context)
        self.assertTrue(response.context["form"].errors)
        transaction.refresh_from_db()
        self.assertEqual(transaction.bank_account_id, self.cash.id)

    def test_bulk_assign_rejects_currency_mismatch(self):
        transaction = create_transaction(
            self.user,
            amount="25.00",
            currency="CZK",
            category=self.category,
            bank_account=self.cash,
        )

        response = self._post_action(
            [transaction],
            extra={
                "apply": "Assign",
                "bank_account": self.euro_account.pk,
            },
        )
        self.assertRedirects(response, self.changelist_url)
        transaction.refresh_from_db()
        self.assertEqual(transaction.bank_account_id, self.cash.id)

    def test_bulk_assign_rejects_multiple_users(self):
        other_user = create_user(username="other")
        other_cash = ensure_cash_bank_account(other_user)
        tx1 = create_transaction(
            self.user,
            amount="25.00",
            currency="EUR",
            category=self.category,
            bank_account=self.cash,
        )
        tx2 = create_transaction(
            other_user,
            amount="30.00",
            currency="EUR",
            category=self.category,
            bank_account=other_cash,
        )
        Transaction.objects.filter(pk__in=[tx1.pk, tx2.pk]).update(currency="EUR")

        response = self._post_action([tx1, tx2])
        self.assertRedirects(response, self.changelist_url)

    def test_bulk_assign_form_filters_bank_accounts_by_user(self):
        other_user = create_user(username="other")
        other_account = create_bank_account(
            other_user,
            name="Other pot",
            currency="EUR",
            kind=BankAccount.SAVINGS,
        )
        transaction = create_transaction(
            self.user,
            amount="25.00",
            currency="EUR",
            category=self.category,
            bank_account=self.cash,
        )
        Transaction.objects.filter(pk=transaction.pk).update(currency="EUR")

        response = self._post_action([transaction])
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        account_ids = {choice.pk for choice in form.fields["bank_account"].queryset}
        self.assertIn(self.euro_account.pk, account_ids)
        self.assertIn(self.cash.pk, account_ids)
        self.assertNotIn(other_account.pk, account_ids)


class AssignTransactionsServiceTests(TestCase):
    def test_assigns_matching_transactions(self):
        user = create_user()
        cash = ensure_cash_bank_account(user)
        euro_account = create_bank_account(
            user,
            name="Euro pot",
            currency="EUR",
            kind=BankAccount.SAVINGS,
        )
        transaction = create_transaction(
            user,
            amount="25.00",
            currency="EUR",
            bank_account=cash,
        )
        Transaction.objects.filter(pk=transaction.pk).update(currency="EUR")

        count = assign_transactions_to_bank_account(
            bank_account=euro_account,
            transactions=Transaction.objects.filter(pk=transaction.pk),
        )
        self.assertEqual(count, 1)
        transaction.refresh_from_db()
        self.assertEqual(transaction.bank_account_id, euro_account.id)

    def test_rejects_different_user(self):
        owner = create_user(username="owner")
        other = create_user(username="other")
        cash = ensure_cash_bank_account(owner)
        other_cash = ensure_cash_bank_account(other)
        transaction = create_transaction(
            owner,
            amount="25.00",
            currency="EUR",
            bank_account=cash,
        )
        Transaction.objects.filter(pk=transaction.pk).update(currency="EUR")

        with self.assertRaises(BankAccountError):
            assign_transactions_to_bank_account(
                bank_account=other_cash,
                transactions=Transaction.objects.filter(pk=transaction.pk),
            )

    def test_rejects_currency_mismatch(self):
        user = create_user()
        cash = ensure_cash_bank_account(user)
        euro_account = create_bank_account(
            user,
            name="Euro pot",
            currency="EUR",
            kind=BankAccount.SAVINGS,
        )
        transaction = create_transaction(
            user,
            amount="25.00",
            currency="CZK",
            bank_account=cash,
        )

        with self.assertRaises(BankAccountError):
            assign_transactions_to_bank_account(
                bank_account=euro_account,
                transactions=Transaction.objects.filter(pk=transaction.pk),
            )

    def test_rejects_mixed_user_selection(self):
        user_a = create_user(username="a")
        user_b = create_user(username="b")
        cash_a = ensure_cash_bank_account(user_a)
        cash_b = ensure_cash_bank_account(user_b)
        tx_a = create_transaction(user_a, amount="10.00", bank_account=cash_a)
        tx_b = create_transaction(user_b, amount="10.00", bank_account=cash_b)

        with self.assertRaises(BankAccountError):
            assign_transactions_to_bank_account(
                bank_account=cash_a,
                transactions=Transaction.objects.filter(pk__in=[tx_a.pk, tx_b.pk]),
            )
