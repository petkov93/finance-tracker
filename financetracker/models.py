from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class Category(models.Model):
    INCOME = "income"
    EXPENSE = "expense"
    TYPE_CHOICES = [
        (INCOME, "Income"),
        (EXPENSE, "Expense"),
    ]

    name = models.CharField(max_length=100)
    icon = models.CharField(max_length=10, default="💰")
    type = models.CharField(max_length=10, choices=TYPE_CHOICES, default=EXPENSE)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["type", "name"]

    def __str__(self):
        return self.name


class Transaction(models.Model):
    INCOME = "income"
    EXPENSE = "expense"
    TYPE_CHOICES = [
        (INCOME, "Income"),
        (EXPENSE, "Expense"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="transactions")
    type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
    description = models.CharField(max_length=255, blank=True)
    date = models.DateField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.get_type_display()} — {self.amount} CZK on {self.date}"


class InvestmentEntry(models.Model):
    INVESTED = "invested"
    PROFIT = "profit"
    TYPE_CHOICES = [
        (INVESTED, "Invested"),
        (PROFIT, "Profit"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="investment_entries")
    type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.CharField(max_length=255, blank=True)
    date = models.DateField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.get_type_display()} — {self.amount} CZK on {self.date}"
