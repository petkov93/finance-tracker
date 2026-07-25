from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import ProtectedError, Q, QuerySet, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from financetracker.models import BankAccount, Transaction, ensure_user_profile
from financetracker.services.currency import get_rates

CASH_BANK_ACCOUNT_NAME = "Cash"
OPENING_BALANCE_DESCRIPTION = "Opening balance"


class BankAccountError(Exception):
    """Raised when a Bank account action would break domain invariants."""


@dataclass(frozen=True)
class AvailableBalanceResult:
    available: Decimal | None
    conversion_degraded: bool
    rates_stale_date: date | None = None


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


def create_bank_account(
    user: User,
    *,
    name: str,
    currency: str,
    kind: str = "",
    opening_balance: Decimal = Decimal("0"),
) -> BankAccount:
    """Create a custom Bank account with optional Opening balance."""
    ensure_user_bank_accounts(user)
    opening_balance = Decimal(opening_balance)
    with transaction.atomic():
        account = BankAccount.objects.create(
            user=user,
            name=name,
            currency=currency,
            kind=kind or "",
            is_cash=False,
        )
        if opening_balance != 0:
            tx_type = (
                Transaction.INCOME if opening_balance > 0 else Transaction.EXPENSE
            )
            opening_tx = Transaction.objects.create(
                user=user,
                bank_account=account,
                type=tx_type,
                amount=abs(opening_balance),
                currency=currency,
                description=OPENING_BALANCE_DESCRIPTION,
                date=timezone.now().date(),
            )
            account.opening_transaction = opening_tx
            account.save(update_fields=["opening_transaction"])
        return account


def rename_bank_account(bank_account: BankAccount, name: str) -> BankAccount:
    bank_account.name = name
    bank_account.save(update_fields=["name"])
    return bank_account


def bank_account_balance(bank_account: BankAccount) -> Decimal:
    """Bank account balance in Bank account currency (may be negative)."""
    aggregates = Transaction.objects.filter(bank_account=bank_account).aggregate(
        income=Coalesce(
            Sum("amount", filter=Q(type=Transaction.INCOME)),
            Decimal("0"),
        ),
        expense=Coalesce(
            Sum("amount", filter=Q(type=Transaction.EXPENSE)),
            Decimal("0"),
        ),
    )
    return aggregates["income"] - aggregates["expense"]


def compute_available_balance(
    user: User,
    default_currency: str | None = None,
) -> AvailableBalanceResult:
    """Available balance: Display-converted sum of Bank account balances.

    Cross-currency Bank accounts use today's latest rate (same policy as open IOUs).
    """
    if default_currency is None:
        default_currency = ensure_user_profile(user).default_currency

    ensure_user_bank_accounts(user)
    accounts = list(BankAccount.objects.filter(user=user))
    account_balances = [
        (bank_account_balance(account), account.currency) for account in accounts
    ]

    rate_keys: set[tuple[str, str, date]] = set()
    for balance, currency in account_balances:
        if currency != default_currency and balance != 0:
            rate_keys.add((currency, default_currency, date.today()))

    rates = get_rates(rate_keys) if rate_keys else {}

    available = Decimal("0")
    conversion_degraded = False
    rates_stale_date: date | None = None

    for balance, currency in account_balances:
        if balance == 0:
            continue
        if currency == default_currency:
            available += balance
            continue

        result = rates.get((currency, default_currency, date.today()))
        if result is None:
            conversion_degraded = True
            continue

        available += balance * result.rate
        if result.stale_date is not None:
            rates_stale_date = (
                max(rates_stale_date, result.stale_date)
                if rates_stale_date is not None
                else result.stale_date
            )

    if conversion_degraded:
        return AvailableBalanceResult(
            available=None,
            conversion_degraded=True,
        )

    return AvailableBalanceResult(
        available=available,
        conversion_degraded=False,
        rates_stale_date=rates_stale_date,
    )


def is_opening_balance_transaction(transaction: Transaction) -> bool:
    try:
        return transaction.opening_for_bank_account is not None
    except BankAccount.DoesNotExist:
        return False


def opening_balance_transaction_ids(user: User) -> set[int]:
    return set(
        BankAccount.objects.filter(
            user=user,
            opening_transaction__isnull=False,
        ).values_list("opening_transaction_id", flat=True)
    )


def exclude_opening_balance_transactions(
    queryset: QuerySet[Transaction],
) -> QuerySet[Transaction]:
    return queryset.filter(opening_for_bank_account__isnull=True)


def exclude_from_spending_statistics(
    queryset: QuerySet[Transaction],
) -> QuerySet[Transaction]:
    """Transactions for Spending statistics / Spending and income totals."""
    from financetracker.services.iou import exclude_iou_linked_transactions

    return exclude_opening_balance_transactions(
        exclude_iou_linked_transactions(queryset)
    )


def bank_account_is_empty(bank_account: BankAccount) -> bool:
    return not Transaction.objects.filter(bank_account=bank_account).exists()


def delete_bank_account(bank_account: BankAccount) -> None:
    if bank_account.is_cash:
        raise BankAccountError("Cash cannot be deleted.")
    if not bank_account_is_empty(bank_account):
        raise BankAccountError(
            "Bank account cannot be deleted while it still has linked transactions."
        )
    try:
        bank_account.delete()
    except ProtectedError as exc:
        raise BankAccountError(
            "Bank account cannot be deleted while it still has linked transactions."
        ) from exc


def _single_user_id_for_transactions(
    transactions: QuerySet[Transaction],
) -> int | None:
    user_ids = set(transactions.values_list("user_id", flat=True))
    if len(user_ids) > 1:
        raise BankAccountError("All selected transactions must belong to the same user.")
    return user_ids.pop() if user_ids else None


def assign_transactions_to_bank_account(
    *,
    bank_account: BankAccount,
    transactions: QuerySet[Transaction],
) -> int:
    """Bulk-assign a queryset of transactions to a Bank account.

    Validates that all transactions belong to the bank account's user and that
    each transaction's currency matches the bank account's currency.
    """
    if not transactions.exists():
        return 0

    user_id = _single_user_id_for_transactions(transactions)
    if user_id is None or bank_account.user_id != user_id:
        raise BankAccountError(
            "Bank account must belong to the same user as the transactions."
        )

    mismatched_count = transactions.exclude(currency=bank_account.currency).count()
    if mismatched_count:
        raise BankAccountError(
            f"{mismatched_count} transaction(s) have a currency that does not match "
            f"the bank account currency ({bank_account.currency})."
        )

    return transactions.update(bank_account=bank_account)
