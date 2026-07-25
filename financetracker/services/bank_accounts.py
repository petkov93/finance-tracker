from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import QuerySet

from financetracker.models import BankAccount, Transaction, ensure_user_profile

CASH_BANK_ACCOUNT_NAME = "Cash"


class BankAccountError(Exception):
    """Raised when a Bank account action would break domain invariants."""


def ensure_cash_bank_account(user: User) -> BankAccount:
    profile = ensure_user_profile(user)
    cash, _created = BankAccount.objects.get_or_create(
        user=user,
        is_cash=True,
        defaults={
            "name": CASH_BANK_ACCOUNT_NAME,
            "currency": profile.default_currency,
            "kind": "",
        },
    )
    return cash


def assign_orphan_transactions_to_cash(user: User) -> int:
    cash = ensure_cash_bank_account(user)
    return Transaction.objects.filter(user=user, bank_account__isnull=True).update(
        bank_account=cash,
    )


def ensure_user_bank_accounts(user: User) -> BankAccount:
    with transaction.atomic():
        cash = ensure_cash_bank_account(user)
        assign_orphan_transactions_to_cash(user)
        return cash


def bank_accounts_for_user(user: User) -> QuerySet[BankAccount]:
    ensure_user_bank_accounts(user)
    return BankAccount.objects.filter(user=user)


def assert_transaction_currency_matches_bank_account(
    *,
    currency: str,
    bank_account: BankAccount,
) -> None:
    if currency != bank_account.currency:
        raise BankAccountError(
            "Transaction currency must match the Bank account currency."
        )


def delete_bank_account(bank_account: BankAccount) -> None:
    if bank_account.is_cash:
        raise BankAccountError("Cash cannot be deleted.")
    try:
        bank_account.delete()
    except ValueError as exc:
        raise BankAccountError(str(exc)) from exc
