from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

from financetracker.admin import BankAccountAdmin
from financetracker.models import BankAccount
from financetracker.services.bank_accounts import ensure_cash_bank_account
from financetracker.tests.factories import create_user


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
