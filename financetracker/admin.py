from django.contrib import admin

from .models import Category, InvestmentEntry, IOU, Transaction, UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "default_currency", "theme"]
    search_fields = ["user__username"]
    raw_id_fields = ["user"]


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "type", "icon"]
    list_filter = ["type"]
    search_fields = ["name"]


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ["date", "type", "amount", "currency", "category", "user", "description"]
    list_filter = ["type", "category", "date"]
    search_fields = ["description"]
    raw_id_fields = ["user", "category"]


@admin.register(InvestmentEntry)
class InvestmentEntryAdmin(admin.ModelAdmin):
    list_display = ["date", "type", "amount", "user", "description"]
    list_filter = ["type", "date"]
    search_fields = ["description"]
    raw_id_fields = ["user"]


@admin.register(IOU)
class IOUAdmin(admin.ModelAdmin):
    list_display = [
        "counterparty_name",
        "direction",
        "remaining_amount",
        "currency",
        "status",
        "due_date",
        "user",
    ]
    list_filter = ["direction", "status"]
    search_fields = ["counterparty_name"]
    raw_id_fields = ["user", "opening_transaction"]
