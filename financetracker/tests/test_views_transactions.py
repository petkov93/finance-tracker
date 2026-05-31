from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from financetracker.models import Transaction
from financetracker.tests.factories import (
    DEFAULT_PASSWORD,
    create_category,
    create_transaction,
    create_user,
)


class TransactionViewsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = create_user()
        self.other_user = create_user(username="bob")
        self.category = create_category()
        self.client.login(username=self.user.username, password=DEFAULT_PASSWORD)

    def test_add_transaction(self):
        response = self.client.post(
            reverse("add_transaction"),
            {
                "type": Transaction.INCOME,
                "amount": "1500.50",
                "category": self.category.pk,
                "description": "Salary",
                "date": "2025-01-15",
            },
        )
        self.assertRedirects(response, reverse("dashboard"))
        transaction = Transaction.objects.get(user=self.user)
        self.assertEqual(transaction.amount, Decimal("1500.50"))
        self.assertEqual(transaction.type, Transaction.INCOME)
        self.assertEqual(transaction.description, "Salary")

    def test_edit_transaction(self):
        transaction = create_transaction(
            self.user,
            amount=Decimal("50.00"),
            description="Lunch",
            category=self.category,
        )
        response = self.client.post(
            reverse("edit_transaction", args=[transaction.pk]),
            {
                "type": Transaction.EXPENSE,
                "amount": "75.00",
                "category": self.category.pk,
                "description": "Updated lunch",
                "date": transaction.date.isoformat(),
            },
        )
        self.assertRedirects(response, reverse("dashboard"))
        transaction.refresh_from_db()
        self.assertEqual(transaction.amount, Decimal("75.00"))
        self.assertEqual(transaction.description, "Updated lunch")

    def test_delete_transaction(self):
        transaction = create_transaction(self.user)
        response = self.client.post(reverse("delete_transaction", args=[transaction.pk]))
        self.assertRedirects(response, reverse("dashboard"))
        self.assertFalse(Transaction.objects.filter(pk=transaction.pk).exists())

    def test_dashboard_balance_calculation(self):
        create_transaction(self.user, amount=Decimal("1000.00"), type=Transaction.INCOME)
        create_transaction(self.user, amount=Decimal("250.00"), type=Transaction.EXPENSE)
        create_transaction(self.user, amount=Decimal("100.00"), type=Transaction.EXPENSE)

        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_income"], Decimal("1000.00"))
        self.assertEqual(response.context["total_expense"], Decimal("350.00"))
        self.assertEqual(response.context["balance"], Decimal("650.00"))

    def test_dashboard_category_filter(self):
        food = create_category(name="Food")
        transport = create_category(name="Transport")
        food_tx = create_transaction(self.user, category=food, description="Groceries")
        create_transaction(self.user, category=transport, description="Bus")

        response = self.client.get(reverse("dashboard"), {"category": food.pk})
        transactions = list(response.context["transactions"])
        self.assertEqual(transactions, [food_tx])

    def test_dashboard_search_filter(self):
        food = create_category(name="Food")
        matching = create_transaction(self.user, category=food, description="Groceries")
        create_transaction(self.user, description="Rent payment")

        response = self.client.get(reverse("dashboard"), {"q": "food"})
        transactions = list(response.context["transactions"])
        self.assertEqual(transactions, [matching])

    def test_user_cannot_edit_other_users_transaction(self):
        other_transaction = create_transaction(self.other_user)
        response = self.client.get(reverse("edit_transaction", args=[other_transaction.pk]))
        self.assertEqual(response.status_code, 404)

    def test_user_cannot_delete_other_users_transaction(self):
        other_transaction = create_transaction(self.other_user)
        response = self.client.post(reverse("delete_transaction", args=[other_transaction.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Transaction.objects.filter(pk=other_transaction.pk).exists())
