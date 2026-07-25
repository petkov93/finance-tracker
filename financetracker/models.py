from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

from financetracker.services.theme_constants import (
    DEFAULT_THEME_PREFERENCE,
    THEME_CHOICES,
)

DEFAULT_PROFILE_CURRENCY = "CZK"
EUR_BASE_CURRENCY = "EUR"
DEFAULT_PROFILE_THEME = DEFAULT_THEME_PREFERENCE


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
    sync_in_progress = models.BooleanField(default=False)
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
    theme = models.CharField(
        max_length=16,
        choices=THEME_CHOICES,
        default=DEFAULT_PROFILE_THEME,
    )

    def __str__(self):
        return f"{self.user.username} — {self.default_currency}"


def ensure_user_profile(user):
    profile, _created = UserProfile.objects.get_or_create(
        user=user,
        defaults={
            "default_currency": DEFAULT_PROFILE_CURRENCY,
            "theme": DEFAULT_PROFILE_THEME,
        },
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


class BankAccountQuerySet(models.QuerySet):
    def delete(self):
        if self.filter(is_cash=True).exists():
            raise ValueError("Cash cannot be deleted.")
        return super().delete()


class BankAccount(models.Model):
    CHECKING = "checking"
    SAVINGS = "savings"
    CREDIT = "credit"
    KIND_CHOICES = [
        (CHECKING, "Checking"),
        (SAVINGS, "Savings"),
        (CREDIT, "Credit"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="bank_accounts")
    name = models.CharField(max_length=100)
    currency = models.CharField(max_length=3)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, blank=True, default="")
    is_cash = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = BankAccountQuerySet.as_manager()

    class Meta:
        ordering = ["-is_cash", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(is_cash=True),
                name="unique_cash_bank_account_per_user",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.currency}) — {self.user.username}"

    def delete(self, using=None, keep_parents=False):
        if self.is_cash:
            raise ValueError("Cash cannot be deleted.")
        return super().delete(using=using, keep_parents=keep_parents)


class Transaction(models.Model):
    INCOME = "income"
    EXPENSE = "expense"
    TYPE_CHOICES = [
        (INCOME, "Income"),
        (EXPENSE, "Expense"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="transactions")
    bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.PROTECT,
        related_name="transactions",
    )
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


class IOU(models.Model):
    RECEIVABLE = "receivable"
    PAYABLE = "payable"
    DIRECTION_CHOICES = [
        (RECEIVABLE, "Receivable"),
        (PAYABLE, "Payable"),
    ]

    ACTIVE = "active"
    PAID = "paid"
    UNPAID = "unpaid"
    STATUS_CHOICES = [
        (ACTIVE, "Active"),
        (PAID, "Paid"),
        (UNPAID, "Unpaid"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="ious")
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES)
    counterparty_name = models.CharField(max_length=255)
    original_amount = models.DecimalField(max_digits=12, decimal_places=2)
    remaining_amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default=DEFAULT_PROFILE_CURRENCY)
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=ACTIVE)
    opening_transaction = models.OneToOneField(
        Transaction,
        on_delete=models.PROTECT,
        related_name="opening_iou",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "IOU"

    def __str__(self):
        return (
            f"{self.get_direction_display()} — {self.remaining_amount} "
            f"{self.currency} from {self.counterparty_name}"
        )


class IOURepayment(models.Model):
    iou = models.ForeignKey(IOU, on_delete=models.CASCADE, related_name="repayments")
    transaction = models.OneToOneField(
        Transaction,
        on_delete=models.PROTECT,
        related_name="iou_repayment",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Repayment of {self.amount} {self.iou.currency} on IOU #{self.iou_id}"


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
