from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from financetracker.models import InvestmentEntry
from financetracker.tests.factories import (
    DEFAULT_PASSWORD,
    create_investment,
    create_user,
)


class InvestmentViewsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = create_user()
        self.other_user = create_user(username="bob")
        self.client.login(username=self.user.username, password=DEFAULT_PASSWORD)

    def test_investments_totals(self):
        create_investment(self.user, amount=Decimal("1000.00"), type=InvestmentEntry.INVESTED)
        create_investment(self.user, amount=Decimal("300.00"), type=InvestmentEntry.PROFIT)
        create_investment(self.user, amount=Decimal("200.00"), type=InvestmentEntry.INVESTED)

        response = self.client.get(reverse("investments"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_invested"], Decimal("1200.00"))
        self.assertEqual(response.context["total_profit"], Decimal("300.00"))
        self.assertEqual(response.context["portfolio_value"], Decimal("-900.00"))
        self.assertEqual(response.context["invested_count"], 2)
        self.assertEqual(response.context["profit_count"], 1)

    def test_investments_formats_amounts_for_accept_language(self):
        create_investment(
            self.user,
            amount=Decimal("1234.56"),
            type=InvestmentEntry.INVESTED,
        )

        response = self.client.get(
            reverse("investments"),
            HTTP_ACCEPT_LANGUAGE="cs-CZ,cs;q=0.9",
        )

        self.assertContains(response, "1\xa0234,56 CZK")

    def test_add_investment(self):
        response = self.client.post(
            reverse("add_investment"),
            {
                "type": InvestmentEntry.INVESTED,
                "amount": "500.00",
                "description": "ETF buy",
                "date": "2025-04-01",
            },
        )
        self.assertRedirects(response, reverse("investments"))
        entry = InvestmentEntry.objects.get(user=self.user)
        self.assertEqual(entry.amount, Decimal("500.00"))
        self.assertEqual(entry.description, "ETF buy")

    def test_edit_investment(self):
        entry = create_investment(self.user, amount=Decimal("100.00"))
        response = self.client.post(
            reverse("edit_investment", args=[entry.pk]),
            {
                "type": InvestmentEntry.PROFIT,
                "amount": "150.00",
                "description": "Dividend",
                "date": entry.date.isoformat(),
            },
        )
        self.assertRedirects(response, reverse("investments"))
        entry.refresh_from_db()
        self.assertEqual(entry.type, InvestmentEntry.PROFIT)
        self.assertEqual(entry.amount, Decimal("150.00"))

    def test_delete_investment(self):
        entry = create_investment(self.user)
        response = self.client.post(reverse("delete_investment", args=[entry.pk]))
        self.assertRedirects(response, reverse("investments"))
        self.assertFalse(InvestmentEntry.objects.filter(pk=entry.pk).exists())

    def test_user_cannot_edit_other_users_investment(self):
        other_entry = create_investment(self.other_user)
        response = self.client.get(reverse("edit_investment", args=[other_entry.pk]))
        self.assertEqual(response.status_code, 404)

    def test_user_cannot_delete_other_users_investment(self):
        other_entry = create_investment(self.other_user)
        response = self.client.post(reverse("delete_investment", args=[other_entry.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(InvestmentEntry.objects.filter(pk=other_entry.pk).exists())
