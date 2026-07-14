from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

DEFAULT_PROFILE_CURRENCY = "CZK"
EUR_BASE_CURRENCY = "EUR"


class ExchangeRate(models.Model):
    base_currency = models.CharField(max_length=3)
    quote_currency = models.CharField(max_length=3)
    rate_date = models.DateField()
    rate = models.DecimalField(max_digits=20, decimal_places=10)
    fetched_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["base_currency", "quote_currency", "rate_date"],
                name="unique_exchange_rate",
            ),
        ]
        indexes = [
            models.Index(fields=["rate_date", "quote_currency"]),
        ]

    def __str__(self):
        return (
            f"{self.base_currency}/{self.quote_currency} "
            f"on {self.rate_date}: {self.rate}"
        )


class SyncMetadata(models.Model):
    last_successful_sync_date = models.DateField(null=True, blank=True)
    supported_currencies = models.JSONField(default=dict)

    @classmethod
    def get_singleton(cls):
        metadata, _created = cls.objects.get_or_create(pk=1)
        return metadata

    def __str__(self):
        return f"Sync metadata (last sync: {self.last_successful_sync_date})"


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    default_currency = models.CharField(max_length=3)

    def __str__(self):
        return f"{self.user.username} — {self.default_currency}"


def ensure_user_profile(user):
    profile, _created = UserProfile.objects.get_or_create(
        user=user,
        defaults={"default_currency": DEFAULT_PROFILE_CURRENCY},
    )
    return profile


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
    currency = models.CharField(max_length=3, default=DEFAULT_PROFILE_CURRENCY)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
    description = models.CharField(max_length=255, blank=True)
    date = models.DateField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.get_type_display()} — {self.amount} {self.currency} on {self.date}"


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
