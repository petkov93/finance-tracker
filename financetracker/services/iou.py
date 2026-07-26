from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Case, DateField, F, IntegerField, QuerySet, Value, When
from django.utils import timezone

from financetracker.models import BankAccount, Category, IOU, IOURepayment, Transaction
from financetracker.services.bank_accounts import (
    BankAccountError,
    assert_transaction_currency_matches_bank_account,
    ensure_cash_bank_account,
)
from financetracker.services.currency import get_rates

LENDING_CATEGORY_NAME = "Lending"
LENDING_CATEGORY_ICON = "🤝"
BORROWING_CATEGORY_NAME = "Borrowing"
BORROWING_CATEGORY_ICON = "💸"
IOU_ALERT_WINDOW_DAYS = 7


class TransactionIouGuardError(Exception):
    """Raised when a ledger action would break IOU invariants."""


def _opening_iou_for(transaction: Transaction) -> IOU | None:
    try:
        return transaction.opening_iou
    except IOU.DoesNotExist:
        return None


def _repayment_for(transaction: Transaction) -> IOURepayment | None:
    try:
        return transaction.iou_repayment
    except IOURepayment.DoesNotExist:
        return None


def is_iou_linked_transaction(transaction: Transaction) -> bool:
    if _opening_iou_for(transaction) is not None:
        return True
    return _repayment_for(transaction) is not None


def exclude_iou_linked_transactions(queryset: QuerySet[Transaction]) -> QuerySet[Transaction]:
    return queryset.filter(opening_iou__isnull=True, iou_repayment__isnull=True)


def iou_linked_transaction_ids(user: User) -> set[int]:
    opening_ids = IOU.objects.filter(user=user).values_list(
        "opening_transaction_id",
        flat=True,
    )
    repayment_ids = IOURepayment.objects.filter(iou__user=user).values_list(
        "transaction_id",
        flat=True,
    )
    return set(opening_ids) | set(repayment_ids)


def active_iou_queryset(user: User, *, direction: str) -> QuerySet[IOU]:
    return (
        IOU.objects.filter(user=user, direction=direction, status=IOU.ACTIVE)
        .select_related("opening_transaction")
        .annotate(
            sort_has_due=Case(
                When(due_date__isnull=False, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            ),
            sort_primary=Case(
                When(due_date__isnull=False, then=F("due_date")),
                default=F("opening_transaction__date"),
                output_field=DateField(),
            ),
        )
        .order_by("sort_has_due", "sort_primary", "-remaining_amount")
    )


def guard_opening_transaction_amount_currency(
    transaction: Transaction,
    *,
    amount: Decimal,
    currency: str,
) -> None:
    iou = _opening_iou_for(transaction)
    if iou is None or iou.status != IOU.ACTIVE:
        return
    stored = Transaction.objects.only("amount", "currency").get(pk=transaction.pk)
    if amount != stored.amount or currency != stored.currency:
        raise TransactionIouGuardError(
            "Cannot change amount or currency on an IOU opening transaction "
            "while the IOU is active."
        )


def delete_transaction_with_iou_effects(tx: Transaction) -> None:
    repayment = _repayment_for(tx)
    if repayment is not None:
        with transaction.atomic():
            iou = repayment.iou
            iou.remaining_amount += repayment.amount
            if iou.status == IOU.PAID and iou.remaining_amount > 0:
                iou.status = IOU.ACTIVE
            iou.save(update_fields=["remaining_amount", "status", "updated_at"])
            repayment.delete()
            tx.delete()
        return

    iou = _opening_iou_for(tx)
    if iou is not None and iou.status == IOU.ACTIVE:
        raise TransactionIouGuardError(
            "Cannot delete the opening transaction while the IOU is active."
        )

    tx.delete()


@dataclass(frozen=True)
class OpenIouAdjustmentResult:
    receivable_total: Decimal
    payable_total: Decimal
    conversion_degraded: bool

    @property
    def net_adjustment(self) -> Decimal | None:
        if self.conversion_degraded:
            return None
        return self.receivable_total - self.payable_total


def ensure_lending_category() -> Category:
    category, _created = Category.objects.get_or_create(
        name=LENDING_CATEGORY_NAME,
        type=Category.EXPENSE,
        defaults={"icon": LENDING_CATEGORY_ICON},
    )
    return category


def ensure_borrowing_category() -> Category:
    category, _created = Category.objects.get_or_create(
        name=BORROWING_CATEGORY_NAME,
        type=Category.INCOME,
        defaults={"icon": BORROWING_CATEGORY_ICON},
    )
    return category


def selectable_categories() -> QuerySet[Category]:
    """Categories users may pick on add/edit transaction (not IOU system categories)."""
    return Category.objects.exclude(
        name__in=[LENDING_CATEGORY_NAME, BORROWING_CATEGORY_NAME],
    )


def _resolve_iou_bank_account(
    user: User,
    *,
    currency: str,
    bank_account: BankAccount | None,
) -> BankAccount:
    account = bank_account if bank_account is not None else ensure_cash_bank_account(user)
    if account.user_id != user.id:
        raise BankAccountError("Bank account must belong to the same user.")
    assert_transaction_currency_matches_bank_account(
        currency=currency,
        bank_account=account,
    )
    return account


def _create_iou(
    user: User,
    *,
    direction: str,
    counterparty_name: str,
    amount: Decimal,
    currency: str,
    due_date: date | None,
    transaction_date: date | None,
    category: Category,
    tx_type: str,
    description: str,
    bank_account: BankAccount | None = None,
) -> IOU:
    on_date = transaction_date or timezone.now().date()
    account = _resolve_iou_bank_account(
        user,
        currency=currency,
        bank_account=bank_account,
    )

    with transaction.atomic():
        opening = Transaction.objects.create(
            user=user,
            bank_account=account,
            type=tx_type,
            amount=amount,
            currency=currency,
            category=category,
            description=description,
            date=on_date,
        )
        return IOU.objects.create(
            user=user,
            direction=direction,
            counterparty_name=counterparty_name,
            original_amount=amount,
            remaining_amount=amount,
            currency=currency,
            due_date=due_date,
            status=IOU.ACTIVE,
            opening_transaction=opening,
        )


def create_receivable(
    user: User,
    *,
    counterparty_name: str,
    amount: Decimal,
    currency: str,
    due_date: date | None = None,
    transaction_date: date | None = None,
    bank_account: BankAccount | None = None,
) -> IOU:
    return _create_iou(
        user,
        direction=IOU.RECEIVABLE,
        counterparty_name=counterparty_name,
        amount=amount,
        currency=currency,
        due_date=due_date,
        transaction_date=transaction_date,
        category=ensure_lending_category(),
        tx_type=Transaction.EXPENSE,
        description=f"Lent to {counterparty_name}",
        bank_account=bank_account,
    )


def create_payable(
    user: User,
    *,
    counterparty_name: str,
    amount: Decimal,
    currency: str,
    due_date: date | None = None,
    transaction_date: date | None = None,
    bank_account: BankAccount | None = None,
) -> IOU:
    return _create_iou(
        user,
        direction=IOU.PAYABLE,
        counterparty_name=counterparty_name,
        amount=amount,
        currency=currency,
        due_date=due_date,
        transaction_date=transaction_date,
        category=ensure_borrowing_category(),
        tx_type=Transaction.INCOME,
        description=f"Borrowed from {counterparty_name}",
        bank_account=bank_account,
    )


def record_repayment(
    iou: IOU,
    *,
    amount: Decimal,
    transaction_date: date | None = None,
    bank_account: BankAccount | None = None,
) -> IOURepayment:
    if iou.status != IOU.ACTIVE:
        raise ValueError("Can only repay active IOUs.")
    if amount <= 0:
        raise ValueError("Repayment amount must be positive.")
    if amount > iou.remaining_amount:
        raise ValueError("Repayment amount cannot exceed remaining amount.")

    on_date = transaction_date or timezone.now().date()
    account = _resolve_iou_bank_account(
        iou.user,
        currency=iou.currency,
        bank_account=bank_account,
    )

    with transaction.atomic():
        if iou.direction == IOU.RECEIVABLE:
            category = ensure_lending_category()
            tx_type = Transaction.INCOME
            description = f"Repayment from {iou.counterparty_name}"
        else:
            category = ensure_borrowing_category()
            tx_type = Transaction.EXPENSE
            description = f"Repayment to {iou.counterparty_name}"

        repayment_tx = Transaction.objects.create(
            user=iou.user,
            bank_account=account,
            type=tx_type,
            amount=amount,
            currency=iou.currency,
            category=category,
            description=description,
            date=on_date,
        )

        iou.remaining_amount -= amount
        if iou.remaining_amount == 0:
            iou.status = IOU.PAID
        iou.save(update_fields=["remaining_amount", "status", "updated_at"])

        return IOURepayment.objects.create(
            iou=iou,
            transaction=repayment_tx,
            amount=amount,
        )


def update_repayment(
    repayment: IOURepayment,
    *,
    amount: Decimal,
    transaction_date: date | None = None,
) -> IOURepayment:
    iou = repayment.iou
    if iou.status != IOU.ACTIVE:
        raise ValueError("Can only edit repayments on active IOUs.")
    if amount <= 0:
        raise ValueError("Repayment amount must be positive.")

    delta = amount - repayment.amount
    new_remaining = iou.remaining_amount - delta
    if new_remaining < 0:
        raise ValueError("Repayment amount cannot exceed remaining amount.")

    on_date = transaction_date or repayment.transaction.date

    with transaction.atomic():
        repayment.amount = amount
        repayment.save(update_fields=["amount"])

        repayment_tx = repayment.transaction
        repayment_tx.amount = amount
        repayment_tx.date = on_date
        repayment_tx.save(update_fields=["amount", "date"])

        iou.remaining_amount = new_remaining
        if new_remaining == 0:
            iou.status = IOU.PAID
        iou.save(update_fields=["remaining_amount", "status", "updated_at"])

    return repayment


@transaction.atomic
def clear_finished_ious(user: User) -> int:
    paid_ious = list(
        IOU.objects.filter(user=user, status=IOU.PAID).prefetch_related("repayments")
    )
    count = len(paid_ious)
    if count == 0:
        return 0

    tx_ids = {iou.opening_transaction_id for iou in paid_ious}
    for iou in paid_ious:
        tx_ids.update(r.transaction_id for r in iou.repayments.all())

    IOU.objects.filter(pk__in=[iou.pk for iou in paid_ious]).delete()
    Transaction.objects.filter(pk__in=tx_ids).delete()
    return count


def close_unpaid(iou: IOU) -> IOU:
    if iou.status != IOU.ACTIVE:
        raise ValueError("Can only close active IOUs as unpaid.")
    iou.status = IOU.UNPAID
    iou.save(update_fields=["status", "updated_at"])
    return iou


def reopen_unpaid(iou: IOU) -> IOU:
    if iou.status != IOU.UNPAID:
        raise ValueError("Can only reopen unpaid IOUs.")
    iou.status = IOU.ACTIVE
    iou.save(update_fields=["status", "updated_at"])
    return iou


def update_iou_metadata(
    iou: IOU,
    *,
    counterparty_name: str,
    due_date: date | None = None,
) -> IOU:
    if iou.status != IOU.ACTIVE:
        raise ValueError("Can only edit metadata on active IOUs.")
    iou.counterparty_name = counterparty_name
    iou.due_date = due_date
    iou.save(update_fields=["counterparty_name", "due_date", "updated_at"])
    return iou


def compute_open_iou_adjustment(
    user: User,
    default_currency: str,
) -> OpenIouAdjustmentResult:
    """Sum open receivable/payable remaining amounts in the default currency.

    Cross-currency open IOUs use today's latest rate (v1 policy).
    """
    active_ious = IOU.objects.filter(user=user, status=IOU.ACTIVE)

    rate_keys: set[tuple[str, str, date]] = set()
    for iou in active_ious:
        if iou.currency != default_currency:
            rate_keys.add((iou.currency, default_currency, date.today()))

    rates = get_rates(rate_keys) if rate_keys else {}

    receivable_total = Decimal("0")
    payable_total = Decimal("0")
    conversion_degraded = False

    for iou in active_ious:
        converted = _convert_iou_amount(iou, default_currency, rates)
        if converted is None:
            conversion_degraded = True
            continue
        if iou.direction == IOU.RECEIVABLE:
            receivable_total += converted
        else:
            payable_total += converted

    if conversion_degraded:
        return OpenIouAdjustmentResult(
            receivable_total=Decimal("0"),
            payable_total=Decimal("0"),
            conversion_degraded=True,
        )

    return OpenIouAdjustmentResult(
        receivable_total=receivable_total,
        payable_total=payable_total,
        conversion_degraded=False,
    )


def _convert_iou_amount(
    iou: IOU,
    default_currency: str,
    rates: dict,
) -> Decimal | None:
    if iou.currency == default_currency:
        return iou.remaining_amount

    result = rates.get((iou.currency, default_currency, date.today()))
    if result is None:
        return None

    return iou.remaining_amount * result.rate


def upcoming_iou_alerts(user: User, *, today: date | None = None) -> list[IOU]:
    on_date = today or timezone.now().date()
    window_end = on_date + timedelta(days=IOU_ALERT_WINDOW_DAYS)
    return list(
        IOU.objects.filter(
            user=user,
            status=IOU.ACTIVE,
            due_date__isnull=False,
            due_date__lte=window_end,
        ).order_by("due_date", "counterparty_name")
    )
