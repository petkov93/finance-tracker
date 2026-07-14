from django.contrib import admin

from .models import Category, InvestmentEntry, Transaction, UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "default_currency"]
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
