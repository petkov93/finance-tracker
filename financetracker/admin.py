from django.contrib import admin, messages
from django.template.response import TemplateResponse

from .forms import AssignBankAccountForm
from .models import BankAccount, Category, InvestmentEntry, IOU, Transaction, UserProfile
from .services.bank_accounts import (
    assign_transactions_to_bank_account,
    BankAccountError,
)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "default_currency", "theme"]
    search_fields = ["user__username"]
    raw_id_fields = ["user"]


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ["name", "currency", "kind", "is_cash", "user"]
    list_filter = ["is_cash", "kind", "currency"]
    search_fields = ["name", "user__username"]
    raw_id_fields = ["user"]

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.is_cash:
            return False
        return super().has_delete_permission(request, obj)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "type", "icon"]
    list_filter = ["type"]
    search_fields = ["name"]


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = [
        "date",
        "type",
        "amount",
        "currency",
        "bank_account",
        "category",
        "user",
        "description",
    ]
    list_filter = ["type", "category", "date"]
    search_fields = ["description"]
    raw_id_fields = ["user", "category", "bank_account"]
    actions = ["assign_transactions_to_bank_account"]

    @admin.action(description="Assign selected transactions to bank account")
    def assign_transactions_to_bank_account(self, request, queryset):
        user_ids = set(queryset.values_list("user_id", flat=True))
        if len(user_ids) > 1:
            self.message_user(
                request,
                "All selected transactions must belong to the same user.",
                level=messages.ERROR,
            )
            return None

        user_id = user_ids.pop() if user_ids else None

        if "apply" in request.POST:
            form = AssignBankAccountForm(request.POST, user_id=user_id)
            if form.is_valid():
                bank_account = form.cleaned_data["bank_account"]
                try:
                    count = assign_transactions_to_bank_account(
                        bank_account=bank_account,
                        transactions=queryset,
                    )
                    self.message_user(
                        request,
                        f"Assigned {count} transaction(s) to {bank_account}.",
                    )
                except BankAccountError as exc:
                    self.message_user(request, str(exc), level=messages.ERROR)
                return None
        else:
            form = AssignBankAccountForm(user_id=user_id)

        context = {
            "title": "Assign transactions to bank account",
            "form": form,
            "queryset": queryset,
            "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME,
            "opts": self.model._meta,
        }
        return TemplateResponse(
            request,
            "admin/financetracker/transaction/assign_bank_account.html",
            context,
        )


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
