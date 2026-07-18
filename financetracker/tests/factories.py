from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User

from financetracker.models import Category, InvestmentEntry, IOU, Transaction

DEFAULT_PASSWORD = "pass1234"


def create_user(username="alice", password=DEFAULT_PASSWORD, email=""):
    return User.objects.create_user(username=username, password=password, email=email)


def create_category(name="Food", type=Category.EXPENSE, icon="🍽️"):
    return Category.objects.create(name=name, type=type, icon=icon)


def create_transaction(
    user,
    *,
    amount=Decimal("100.00"),
    currency="CZK",
    type=Transaction.EXPENSE,
    category=None,
    description="",
    transaction_date=None,
):
    return Transaction.objects.create(
        user=user,
        type=type,
        amount=amount,
        currency=currency,
        category=category,
        description=description,
        date=transaction_date or date.today(),
    )


def create_investment(
    user,
    *,
    amount=Decimal("500.00"),
    type=InvestmentEntry.INVESTED,
    description="",
    entry_date=None,
):
    return InvestmentEntry.objects.create(
        user=user,
        type=type,
        amount=amount,
        description=description,
        date=entry_date or date.today(),
    )


def create_iou(
    user,
    *,
    counterparty_name="Alex",
    amount=Decimal("100.00"),
    currency="CZK",
    direction=IOU.RECEIVABLE,
    status=IOU.ACTIVE,
    due_date=None,
    opening_transaction=None,
):
    if opening_transaction is None:
        tx_type = Transaction.INCOME if direction == IOU.PAYABLE else Transaction.EXPENSE
        opening_transaction = create_transaction(
            user,
            amount=amount,
            currency=currency,
            type=tx_type,
        )
    return IOU.objects.create(
        user=user,
        direction=direction,
        counterparty_name=counterparty_name,
        original_amount=amount,
        remaining_amount=amount,
        currency=currency,
        due_date=due_date,
        status=status,
        opening_transaction=opening_transaction,
    )
