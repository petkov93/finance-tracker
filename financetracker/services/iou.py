from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from financetracker.models import Category, IOU, Transaction
from financetracker.services.currency import get_rates

LENDING_CATEGORY_NAME = "Lending"
LENDING_CATEGORY_ICON = "🤝"
BORROWING_CATEGORY_NAME = "Borrowing"
BORROWING_CATEGORY_ICON = "💸"


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


def create_receivable(
    user: User,
    *,
    counterparty_name: str,
    amount: Decimal,
    currency: str,
    due_date: date | None = None,
    transaction_date: date | None = None,
) -> IOU:
    lending_category = ensure_lending_category()
    on_date = transaction_date or timezone.now().date()

    with transaction.atomic():
        opening = Transaction.objects.create(
            user=user,
            type=Transaction.EXPENSE,
            amount=amount,
            currency=currency,
            category=lending_category,
            description=f"Lent to {counterparty_name}",
            date=on_date,
        )
        return IOU.objects.create(
            user=user,
            direction=IOU.RECEIVABLE,
            counterparty_name=counterparty_name,
            original_amount=amount,
            remaining_amount=amount,
            currency=currency,
            due_date=due_date,
            status=IOU.ACTIVE,
            opening_transaction=opening,
        )


def create_payable(
    user: User,
    *,
    counterparty_name: str,
    amount: Decimal,
    currency: str,
    due_date: date | None = None,
    transaction_date: date | None = None,
) -> IOU:
    borrowing_category = ensure_borrowing_category()
    on_date = transaction_date or timezone.now().date()

    with transaction.atomic():
        opening = Transaction.objects.create(
            user=user,
            type=Transaction.INCOME,
            amount=amount,
            currency=currency,
            category=borrowing_category,
            description=f"Borrowed from {counterparty_name}",
            date=on_date,
        )
        return IOU.objects.create(
            user=user,
            direction=IOU.PAYABLE,
            counterparty_name=counterparty_name,
            original_amount=amount,
            remaining_amount=amount,
            currency=currency,
            due_date=due_date,
            status=IOU.ACTIVE,
            opening_transaction=opening,
        )


def compute_open_iou_adjustment(
    user: User,
    default_currency: str,
) -> OpenIouAdjustmentResult:
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
