import json
from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.db import transaction
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST
from .models import (
    BankAccount,
    Transaction,
    Category,
    InvestmentEntry,
    IOU,
    IOURepayment,
    UserProfile,
    ensure_user_profile,
)
from .services.bank_accounts import (
    BankAccountError,
    bank_account_balance,
    bank_account_is_empty,
    bank_accounts_for_user,
    create_bank_account,
    delete_bank_account,
    ensure_user_bank_accounts,
    exclude_from_spending_statistics,
    is_opening_balance_transaction,
    opening_balance_transaction_ids,
    rename_bank_account,
)
from .services.theme_constants import THEME_CHOICES
from .services.theme_preference import for_request, set_preference
from .forms import (
    BankAccountCreateForm,
    BankAccountRenameForm,
    CurrencyConverterForm,
    CustomPasswordChangeForm,
    DefaultCurrencyForm,
    InvestmentEntryForm,
    LendForm,
    BorrowForm,
    RepayForm,
    IOUMetadataForm,
    ProfileForm,
    RegistrationForm,
    TransactionForm,
    build_currency_choices,
)
from .services.conversion_pair import (
    ConversionPair,
    remember_conversion_pair,
    resolve_conversion_pair,
)
from .services.currency import (
    CurrencyConversionError,
    convert,
    get_rate,
    get_supported_currencies,
)
from .services.display_conversion import convert_for_display
from .services.iou import (
    TransactionIouGuardError,
    active_iou_queryset,
    clear_finished_ious,
    close_unpaid,
    compute_open_iou_adjustment,
    create_payable,
    create_receivable,
    delete_transaction_with_iou_effects,
    guard_opening_transaction_amount_currency,
    iou_linked_transaction_ids,
    is_iou_linked_transaction,
    record_repayment,
    reopen_unpaid,
    selectable_categories,
    update_iou_metadata,
    update_repayment,
)
from .services.statistics_aggregation import aggregate_for_statistics


def landing(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    return render(request, "financetracker/landing.html")


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            ensure_user_profile(user)
            ensure_user_bank_accounts(user)
            login(request, user)
            next_url = request.GET.get("next")
            if next_url and url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                return redirect(next_url)
            return redirect("dashboard")
        messages.error(request, "Invalid username or password.")
    else:
        form = AuthenticationForm()
    return render(request, "financetracker/login.html", {"form": form})


@require_POST
def logout_view(request):
    logout(request)
    return redirect("login")


def register_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    try:
        supported = get_supported_currencies()
    except CurrencyConversionError:
        messages.error(
            request,
            "Couldn't load supported currencies right now. Try again in a moment.",
        )
        return render(
            request,
            "financetracker/register.html",
            {"form": None, "currency_error": True},
            status=200,
        )

    currency_choices = build_currency_choices(supported)

    if request.method == "POST":
        form = RegistrationForm(request.POST, currency_choices=currency_choices)
        if form.is_valid():
            with transaction.atomic():
                user = form.save()
                UserProfile.objects.create(
                    user=user,
                    default_currency=form.cleaned_data["default_currency"],
                )
                ensure_user_bank_accounts(user)
            login(request, user)
            messages.success(request, f"Welcome, {user.username}! Your account has been created.")
            return redirect("dashboard")
    else:
        form = RegistrationForm(currency_choices=currency_choices)

    return render(
        request,
        "financetracker/register.html",
        {
            "form": form,
            "supported_currency_codes_json": json.dumps(sorted(supported.keys())),
        },
    )


@login_required
def dashboard(request):
    qs = Transaction.objects.filter(user=request.user).select_related("category")
    all_categories = Category.objects.all()
    
    # Filtering
    category_id = request.GET.get("category")
    q_query = request.GET.get("q", "")

    if category_id:
        qs = qs.filter(category__id=category_id)
    if q_query:
        qs = qs.filter(Q(description__icontains=q_query) | Q(category__name__icontains=q_query))
    
    profile = ensure_user_profile(request.user)
    all_transactions = Transaction.objects.filter(user=request.user)
    spending_transactions = exclude_from_spending_statistics(all_transactions)
    linked_ids = (
        iou_linked_transaction_ids(request.user)
        | opening_balance_transaction_ids(request.user)
    )
    display = convert_for_display(
        qs,
        profile.default_currency,
        totals_transactions=all_transactions,
        spending_totals_transactions=spending_transactions,
        iou_linked_transaction_ids=linked_ids,
    )

    conversion_degraded = display.conversion_degraded
    available = None
    total = None

    if not conversion_degraded:
        iou_adjustment = compute_open_iou_adjustment(
            request.user,
            profile.default_currency,
        )
        if iou_adjustment.conversion_degraded:
            conversion_degraded = True
        else:
            available = display.balance
            total = available + iou_adjustment.net_adjustment

    return render(request, "financetracker/dashboard.html", {
        "display_transactions": display.rows,
        "all_categories": all_categories,
        "selected_category": category_id,
        "q_query": q_query,
        "total_income": display.total_income,
        "total_expense": display.total_expense,
        "available": available,
        "total": total,
        "default_currency": display.default_currency,
        "conversion_degraded": conversion_degraded,
        "rates_stale_date": display.rates_stale_date,
    })


def _transaction_currency_context(request):
    try:
        supported = get_supported_currencies()
    except CurrencyConversionError:
        return None
    profile = ensure_user_profile(request.user)
    currency_choices = build_currency_choices(supported)
    return {
        "currency_choices": currency_choices,
        "default_currency": profile.default_currency,
    }


@login_required
def add_transaction(request):
    currency_context = _transaction_currency_context(request)
    if currency_context is None:
        messages.error(
            request,
            "Couldn't load supported currencies right now. Try again in a moment.",
        )
        return render(
            request,
            "financetracker/add_transaction.html",
            {
                "form": None,
                "currency_error": True,
                "title": "Add Transaction",
                "all_categories": selectable_categories(),
            },
            status=200,
        )

    if request.method == "POST":
        form = TransactionForm(
            request.POST,
            user=request.user,
            currency_choices=currency_context["currency_choices"],
            default_currency=currency_context["default_currency"],
        )
        if form.is_valid():
            t = form.save(commit=False)
            t.user = request.user
            t.save()
            messages.success(request, "Transaction added successfully.")
            return redirect("dashboard")
    else:
        form = TransactionForm(
            initial={
                "date": timezone.now().date(),
                "currency": currency_context["default_currency"],
            },
            user=request.user,
            currency_choices=currency_context["currency_choices"],
            default_currency=currency_context["default_currency"],
        )
    return render(request, "financetracker/add_transaction.html", {
        "form": form,
        "title": "Add Transaction",
        "all_categories": selectable_categories(),
    })


@login_required
def edit_transaction(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk, user=request.user)
    if is_opening_balance_transaction(transaction):
        messages.error(
            request,
            "Opening balance cannot be edited.",
        )
        return redirect("dashboard")
    if is_iou_linked_transaction(transaction):
        messages.error(
            request,
            "IOU-linked transactions cannot be edited from the dashboard. "
            "Manage repayments on the IOU detail page.",
        )
        return redirect("dashboard")
    currency_context = _transaction_currency_context(request)
    if currency_context is None:
        messages.error(
            request,
            "Couldn't load supported currencies right now. Try again in a moment.",
        )
        return render(
            request,
            "financetracker/add_transaction.html",
            {
                "form": None,
                "currency_error": True,
                "title": "Edit Transaction",
                "transaction": transaction,
                "all_categories": selectable_categories(),
            },
            status=200,
        )

    if request.method == "POST":
        form = TransactionForm(
            request.POST,
            instance=transaction,
            user=request.user,
            currency_choices=currency_context["currency_choices"],
        )
        if form.is_valid():
            try:
                guard_opening_transaction_amount_currency(
                    transaction,
                    amount=form.cleaned_data["amount"],
                    currency=form.cleaned_data["currency"],
                )
            except TransactionIouGuardError as exc:
                form.add_error(None, str(exc))
            else:
                form.save()
                messages.success(request, "Transaction updated.")
                return redirect("dashboard")
    else:
        form = TransactionForm(
            instance=transaction,
            user=request.user,
            currency_choices=currency_context["currency_choices"],
        )
    return render(request, "financetracker/add_transaction.html", {
        "form": form,
        "title": "Edit Transaction",
        "transaction": transaction,
        "all_categories": selectable_categories(),
    })


@login_required
@require_POST
def delete_transaction(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk, user=request.user)
    if is_opening_balance_transaction(transaction):
        messages.error(
            request,
            "Opening balance cannot be deleted.",
        )
        return redirect("dashboard")
    if is_iou_linked_transaction(transaction):
        messages.error(
            request,
            "IOU-linked transactions cannot be deleted from the dashboard. "
            "Manage repayments on the IOU detail page.",
        )
        return redirect("dashboard")
    try:
        delete_transaction_with_iou_effects(transaction)
    except TransactionIouGuardError as exc:
        messages.error(request, str(exc))
        return redirect("dashboard")
    messages.success(request, "Transaction deleted.")
    return redirect("dashboard")


@login_required
def statistics(request):
    qs = Transaction.objects.filter(user=request.user).select_related("category")

    # Date range for monthly chart — default to current year
    today = date.today()
    default_from = date(today.year, 1, 1)
    default_to = today

    from_date_str = request.GET.get("from_date", "")
    to_date_str   = request.GET.get("to_date", "")

    try:
        from_date = date.fromisoformat(from_date_str) if from_date_str else default_from
    except ValueError:
        from_date = default_from

    try:
        to_date = date.fromisoformat(to_date_str) if to_date_str else default_to
    except ValueError:
        to_date = default_to

    if from_date > to_date:
        from_date, to_date = to_date, from_date

    qs_filtered = qs.filter(date__gte=from_date, date__lte=to_date)
    spending_qs = exclude_from_spending_statistics(qs_filtered)

    profile = ensure_user_profile(request.user)
    display = convert_for_display(
        spending_qs,
        profile.default_currency,
        totals_transactions=spending_qs,
    )

    total_count   = spending_qs.count()
    income_count  = spending_qs.filter(type="income").count()
    expense_count = spending_qs.filter(type="expense").count()

    aggregation = aggregate_for_statistics(display)

    total_income = (
        float(display.total_income) if display.total_income is not None else None
    )
    total_expense = (
        float(display.total_expense) if display.total_expense is not None else None
    )
    balance = float(display.balance) if display.balance is not None else None

    return render(request, "financetracker/statistics.html", {
        "month_labels":       json.dumps(aggregation.month_labels),
        "monthly_income":     json.dumps(
            [float(v) for v in aggregation.monthly_income]
        ),
        "monthly_expense":    json.dumps(
            [float(v) for v in aggregation.monthly_expense]
        ),
        "cat_labels":         json.dumps(aggregation.expense_category_labels),
        "cat_values":         json.dumps(
            [float(v) for v in aggregation.expense_category_values]
        ),
        "income_cat_labels":  json.dumps(aggregation.income_category_labels),
        "income_cat_values":  json.dumps(
            [float(v) for v in aggregation.income_category_values]
        ),
        "has_expense_categories": aggregation.has_expense_categories,
        "has_income_categories": aggregation.has_income_categories,
        "total_income":       total_income,
        "total_expense":      total_expense,
        "balance":            balance,
        "total_count":        total_count,
        "income_count":       income_count,
        "expense_count":      expense_count,
        "from_date":          from_date.isoformat(),
        "to_date":            to_date.isoformat(),
        "default_currency":   display.default_currency,
        "conversion_degraded": display.conversion_degraded,
        "rates_stale_date": display.rates_stale_date,
    })


@login_required
def investments(request):
    qs = InvestmentEntry.objects.filter(user=request.user)
    entries = qs[:20]
    totals = qs.aggregate(
        total_invested=Sum("amount", filter=Q(type="invested")),
        total_profit=Sum("amount", filter=Q(type="profit")),
    )
    total_invested = totals["total_invested"] or Decimal("0")
    total_profit = totals["total_profit"] or Decimal("0")
    portfolio_value = total_profit - total_invested

    invested_count = qs.filter(type="invested").count()
    profit_count = qs.filter(type="profit").count()

    return render(request, "financetracker/investments.html", {
        "entries": entries,
        "total_invested": total_invested,
        "total_profit": total_profit,
        "portfolio_value": portfolio_value,
        "invested_count": invested_count,
        "profit_count": profit_count,
        "entry_count": qs.count(),
    })


@login_required
def add_investment(request):
    if request.method == "POST":
        form = InvestmentEntryForm(request.POST)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.user = request.user
            entry.save()
            messages.success(request, "Investment entry added successfully.")
            return redirect("investments")
    else:
        form = InvestmentEntryForm(initial={"date": timezone.now().date()})
    return render(request, "financetracker/add_investment.html", {
        "form": form,
        "title": "Add Investment Entry",
    })


@login_required
def edit_investment(request, pk):
    entry = get_object_or_404(InvestmentEntry, pk=pk, user=request.user)
    if request.method == "POST":
        form = InvestmentEntryForm(request.POST, instance=entry)
        if form.is_valid():
            form.save()
            messages.success(request, "Investment entry updated.")
            return redirect("investments")
    else:
        form = InvestmentEntryForm(instance=entry)
    return render(request, "financetracker/add_investment.html", {
        "form": form,
        "title": "Edit Investment Entry",
        "entry": entry,
    })


@login_required
@require_POST
def delete_investment(request, pk):
    entry = get_object_or_404(InvestmentEntry, pk=pk, user=request.user)
    entry.delete()
    messages.success(request, "Investment entry deleted.")
    return redirect("investments")


@login_required
def bank_accounts(request):
    accounts = bank_accounts_for_user(request.user)
    account_rows = [
        {
            "account": account,
            "balance": bank_account_balance(account),
            "can_delete": (not account.is_cash and bank_account_is_empty(account)),
        }
        for account in accounts
    ]
    return render(
        request,
        "financetracker/bank_accounts.html",
        {"account_rows": account_rows},
    )


@login_required
def add_bank_account(request):
    currency_context = _transaction_currency_context(request)
    if currency_context is None:
        messages.error(
            request,
            "Couldn't load supported currencies right now. Try again in a moment.",
        )
        return render(
            request,
            "financetracker/add_bank_account.html",
            {"form": None, "currency_error": True},
            status=200,
        )

    if request.method == "POST":
        form = BankAccountCreateForm(
            request.POST,
            currency_choices=currency_context["currency_choices"],
        )
        if form.is_valid():
            create_bank_account(
                request.user,
                name=form.cleaned_data["name"],
                currency=form.cleaned_data["currency"],
                kind=form.cleaned_data["kind"],
                opening_balance=form.cleaned_data["opening_balance"],
            )
            messages.success(request, "Bank account created.")
            return redirect("bank_accounts")
    else:
        form = BankAccountCreateForm(
            currency_choices=currency_context["currency_choices"],
            default_currency=currency_context["default_currency"],
        )

    return render(
        request,
        "financetracker/add_bank_account.html",
        {"form": form},
    )


@login_required
def edit_bank_account(request, pk):
    account = get_object_or_404(
        BankAccount,
        pk=pk,
        user=request.user,
        is_cash=False,
    )
    if request.method == "POST":
        form = BankAccountRenameForm(request.POST)
        if form.is_valid():
            rename_bank_account(account, form.cleaned_data["name"])
            messages.success(request, "Bank account renamed.")
            return redirect("bank_accounts")
    else:
        form = BankAccountRenameForm(initial={"name": account.name})

    return render(
        request,
        "financetracker/edit_bank_account.html",
        {"form": form, "account": account},
    )


@login_required
@require_POST
def delete_bank_account_view(request, pk):
    account = get_object_or_404(BankAccount, pk=pk, user=request.user)
    try:
        delete_bank_account(account)
    except BankAccountError as exc:
        messages.error(request, str(exc))
        return redirect("bank_accounts")
    messages.success(request, "Bank account deleted.")
    return redirect("bank_accounts")


@login_required
def ious(request):
    receivables = active_iou_queryset(request.user, direction=IOU.RECEIVABLE)
    payables = active_iou_queryset(request.user, direction=IOU.PAYABLE)
    closed_ious = IOU.objects.filter(
        user=request.user,
        status__in=[IOU.PAID, IOU.UNPAID],
    )
    return render(request, "financetracker/ious.html", {
        "receivables": receivables,
        "receivable_count": receivables.count(),
        "payables": payables,
        "payable_count": payables.count(),
        "closed_ious": closed_ious,
        "closed_count": closed_ious.count(),
    })


@login_required
def add_lend(request):
    currency_context = _transaction_currency_context(request)
    if currency_context is None:
        messages.error(
            request,
            "Couldn't load supported currencies right now. Try again in a moment.",
        )
        return render(
            request,
            "financetracker/add_iou.html",
            {
                "form": None,
                "currency_error": True,
                "title": "Lend money",
                "submit_label": "Record lend",
            },
            status=200,
        )

    if request.method == "POST":
        form = LendForm(
            request.POST,
            currency_choices=currency_context["currency_choices"],
        )
        if form.is_valid():
            create_receivable(
                request.user,
                counterparty_name=form.cleaned_data["counterparty_name"],
                amount=form.cleaned_data["amount"],
                currency=form.cleaned_data["currency"],
                due_date=form.cleaned_data.get("due_date"),
                transaction_date=form.cleaned_data["date"],
            )
            messages.success(request, "Lending recorded successfully.")
            return redirect("ious")
    else:
        form = LendForm(
            initial={
                "date": timezone.now().date(),
                "currency": currency_context["default_currency"],
            },
            currency_choices=currency_context["currency_choices"],
            default_currency=currency_context["default_currency"],
        )

    return render(request, "financetracker/add_iou.html", {
        "form": form,
        "title": "Lend money",
        "submit_label": "Record lend",
    })


@login_required
def add_borrow(request):
    currency_context = _transaction_currency_context(request)
    if currency_context is None:
        messages.error(
            request,
            "Couldn't load supported currencies right now. Try again in a moment.",
        )
        return render(
            request,
            "financetracker/add_iou.html",
            {
                "form": None,
                "currency_error": True,
                "title": "Borrow money",
                "submit_label": "Record borrow",
            },
            status=200,
        )

    if request.method == "POST":
        form = BorrowForm(
            request.POST,
            currency_choices=currency_context["currency_choices"],
        )
        if form.is_valid():
            create_payable(
                request.user,
                counterparty_name=form.cleaned_data["counterparty_name"],
                amount=form.cleaned_data["amount"],
                currency=form.cleaned_data["currency"],
                due_date=form.cleaned_data.get("due_date"),
                transaction_date=form.cleaned_data["date"],
            )
            messages.success(request, "Borrowing recorded successfully.")
            return redirect("ious")
    else:
        form = BorrowForm(
            initial={
                "date": timezone.now().date(),
                "currency": currency_context["default_currency"],
            },
            currency_choices=currency_context["currency_choices"],
            default_currency=currency_context["default_currency"],
        )

    return render(request, "financetracker/add_iou.html", {
        "form": form,
        "title": "Borrow money",
        "submit_label": "Record borrow",
    })


@login_required
def iou_detail(request, pk):
    iou = get_object_or_404(IOU, pk=pk, user=request.user)
    repayments = iou.repayments.select_related("transaction").order_by(
        "-transaction__date",
        "-created_at",
    )

    repay_form = None
    metadata_form = None

    if request.method == "POST":
        action = request.POST.get("action", "repay")

        if action == "close_unpaid":
            if iou.status != IOU.ACTIVE:
                messages.error(request, "Only active IOUs can be closed as unpaid.")
            else:
                close_unpaid(iou)
                messages.success(request, "IOU closed as unpaid.")
            return redirect("iou_detail", pk=pk)

        if action == "reopen":
            if iou.status != IOU.UNPAID:
                messages.error(request, "Only unpaid IOUs can be reopened.")
            else:
                reopen_unpaid(iou)
                messages.success(request, "IOU reopened.")
            return redirect("iou_detail", pk=pk)

        if action == "edit_metadata":
            if iou.status != IOU.ACTIVE:
                messages.error(request, "Only active IOUs can be edited.")
                return redirect("iou_detail", pk=pk)

            metadata_form = IOUMetadataForm(request.POST)
            if metadata_form.is_valid():
                update_iou_metadata(
                    iou,
                    counterparty_name=metadata_form.cleaned_data["counterparty_name"],
                    due_date=metadata_form.cleaned_data.get("due_date"),
                )
                messages.success(request, "IOU details updated.")
                return redirect("iou_detail", pk=pk)
        elif action == "edit_repayment":
            if iou.status != IOU.ACTIVE:
                messages.error(request, "Only active IOUs accept repayment changes.")
                return redirect("iou_detail", pk=pk)

            repayment = get_object_or_404(
                IOURepayment,
                pk=request.POST.get("repayment_id"),
                iou=iou,
            )
            repay_form = RepayForm(
                request.POST,
                max_amount=iou.remaining_amount + repayment.amount,
                currency=iou.currency,
            )
            if repay_form.is_valid():
                try:
                    update_repayment(
                        repayment,
                        amount=repay_form.cleaned_data["amount"],
                        transaction_date=repay_form.cleaned_data["date"],
                    )
                except ValueError as exc:
                    messages.error(request, str(exc))
                    return redirect("iou_detail", pk=pk)
                messages.success(request, "Repayment updated.")
                return redirect("iou_detail", pk=pk)
        elif action == "delete_repayment":
            if iou.status not in (IOU.ACTIVE, IOU.PAID):
                messages.error(
                    request,
                    "Only active or paid IOUs accept repayment deletion.",
                )
                return redirect("iou_detail", pk=pk)

            repayment = get_object_or_404(
                IOURepayment,
                pk=request.POST.get("repayment_id"),
                iou=iou,
            )
            delete_transaction_with_iou_effects(repayment.transaction)
            messages.success(request, "Repayment deleted.")
            return redirect("iou_detail", pk=pk)
        elif action == "repay":
            if iou.status != IOU.ACTIVE:
                messages.error(request, "This IOU is closed and cannot accept repayments.")
                return redirect("iou_detail", pk=pk)

            repay_form = RepayForm(
                request.POST,
                max_amount=iou.remaining_amount,
                currency=iou.currency,
            )
            if repay_form.is_valid():
                try:
                    record_repayment(
                        iou,
                        amount=repay_form.cleaned_data["amount"],
                        transaction_date=repay_form.cleaned_data["date"],
                    )
                except ValueError as exc:
                    messages.error(request, str(exc))
                    return redirect("iou_detail", pk=pk)
                messages.success(request, "Repayment recorded successfully.")
                return redirect("iou_detail", pk=pk)
    else:
        if iou.status == IOU.ACTIVE:
            repay_form = RepayForm(
                initial={"date": timezone.now().date()},
                max_amount=iou.remaining_amount,
                currency=iou.currency,
            )
            metadata_form = IOUMetadataForm(
                initial={
                    "counterparty_name": iou.counterparty_name,
                    "due_date": iou.due_date,
                },
            )

    if iou.status == IOU.ACTIVE:
        if repay_form is None:
            repay_form = RepayForm(
                initial={"date": timezone.now().date()},
                max_amount=iou.remaining_amount,
                currency=iou.currency,
            )
        if metadata_form is None:
            metadata_form = IOUMetadataForm(
                initial={
                    "counterparty_name": iou.counterparty_name,
                    "due_date": iou.due_date,
                },
            )

    return render(request, "financetracker/iou_detail.html", {
        "iou": iou,
        "repayments": repayments,
        "repay_form": repay_form,
        "metadata_form": metadata_form,
    })


@login_required
def settings_view(request):
    profile = ensure_user_profile(request.user)
    try:
        supported = get_supported_currencies()
    except CurrencyConversionError:
        messages.error(
            request,
            "Couldn't load supported currencies right now. Try again in a moment.",
        )
        return render(
            request,
            "financetracker/settings.html",
            {
                "profile_form": ProfileForm(instance=request.user),
                "password_form": CustomPasswordChangeForm(user=request.user),
                "currency_form": None,
                "currency_error": True,
                "theme_choices": THEME_CHOICES,
                "selected_theme": for_request(request),
                "transaction_count": Transaction.objects.filter(user=request.user).count(),
                "investment_count": InvestmentEntry.objects.filter(user=request.user).count(),
                "finished_iou_count": IOU.objects.filter(
                    user=request.user,
                    status=IOU.PAID,
                ).count(),
            },
            status=200,
        )

    currency_choices = build_currency_choices(supported)
    profile_form = ProfileForm(instance=request.user)
    password_form = CustomPasswordChangeForm(user=request.user)
    currency_form = DefaultCurrencyForm(instance=profile, currency_choices=currency_choices)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "profile":
            profile_form = ProfileForm(request.POST, instance=request.user)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Account details updated.")
                return redirect("settings")
        elif action == "password":
            password_form = CustomPasswordChangeForm(user=request.user, data=request.POST)
            if password_form.is_valid():
                password_form.save()
                update_session_auth_hash(request, password_form.user)
                messages.success(request, "Password changed successfully.")
                return redirect("settings")
        elif action == "currency":
            currency_form = DefaultCurrencyForm(
                request.POST,
                instance=profile,
                currency_choices=currency_choices,
            )
            if currency_form.is_valid():
                currency_form.save()
                messages.success(request, "Default currency updated.")
                return redirect("settings")
        elif action == "theme":
            theme = (request.POST.get("theme") or "").strip()
            try:
                set_preference(request.user, theme)
            except ValueError:
                messages.error(request, "Invalid appearance choice.")
                return redirect("settings")
            messages.success(request, "Appearance updated.")
            return redirect("settings")

    return render(request, "financetracker/settings.html", {
        "profile_form": profile_form,
        "password_form": password_form,
        "currency_form": currency_form,
        "theme_choices": THEME_CHOICES,
        "selected_theme": for_request(request),
        "transaction_count": exclude_from_spending_statistics(
            Transaction.objects.filter(user=request.user)
        ).count(),
        "investment_count": InvestmentEntry.objects.filter(user=request.user).count(),
        "finished_iou_count": IOU.objects.filter(
            user=request.user,
            status=IOU.PAID,
        ).count(),
    })


@login_required
@require_POST
def clear_all_transactions(request):
    qs = exclude_from_spending_statistics(Transaction.objects.filter(user=request.user))
    count = qs.count()
    qs.delete()
    messages.success(request, f"Deleted all {count} transaction(s).")
    return redirect("settings")


@login_required
@require_POST
def clear_all_investments(request):
    count = InvestmentEntry.objects.filter(user=request.user).count()
    InvestmentEntry.objects.filter(user=request.user).delete()
    messages.success(request, f"Deleted all {count} investment entr{'y' if count == 1 else 'ies'}.")
    return redirect("settings")


@login_required
@require_POST
def clear_finished_ious_view(request):
    count = clear_finished_ious(request.user)
    messages.success(
        request,
        f"Deleted {count} finished IOU record{'s' if count != 1 else ''} "
        "and their linked transactions.",
    )
    return redirect("settings")


def _currency_choices(supported):
    return build_currency_choices(supported)


def _quantize_money(value):
    return value.quantize(Decimal("0.01"))


def _quantize_rate(value):
    return value.quantize(Decimal("0.0001"))


def _rate_json(from_currency, to_currency, rate, *, stale_date=None):
    payload = {
        "from": from_currency,
        "to": to_currency,
        "rate": format(_quantize_rate(rate), "f"),
    }
    if stale_date is not None:
        payload["rates_stale_date"] = stale_date.isoformat()
    return payload


def _validate_api_currencies(from_currency, to_currency, supported):
    from_code = (from_currency or "").upper()
    to_code = (to_currency or "").upper()
    if from_code not in supported or to_code not in supported:
        return None, JsonResponse({"error": "Unsupported currency code."}, status=400)
    return (from_code, to_code), None


def _parse_convert_amount(raw_amount):
    if raw_amount is None or raw_amount == "":
        return None, JsonResponse({"error": "Enter an amount to convert."}, status=400)
    try:
        amount = Decimal(str(raw_amount))
    except Exception:
        return None, JsonResponse({"error": "Enter a valid amount."}, status=400)
    if amount <= 0:
        return None, JsonResponse({"error": "Amount must be greater than zero."}, status=400)
    return amount, None


@login_required
@require_GET
def converter_rate_api(request):
    try:
        supported = get_supported_currencies()
    except CurrencyConversionError:
        return JsonResponse(
            {"error": "Couldn't load supported currencies right now."},
            status=503,
        )

    pair, error_response = _validate_api_currencies(
        request.GET.get("from"),
        request.GET.get("to"),
        supported,
    )
    if error_response:
        return error_response
    from_currency, to_currency = pair

    try:
        rate_result = get_rate(from_currency, to_currency)
    except CurrencyConversionError:
        return JsonResponse(
            {"error": "Couldn't fetch the exchange rate right now."},
            status=503,
        )

    return JsonResponse(
        _rate_json(
            from_currency,
            to_currency,
            rate_result.rate,
            stale_date=rate_result.stale_date,
        )
    )


@login_required
@require_POST
def converter_convert_api(request):
    try:
        supported = get_supported_currencies()
    except CurrencyConversionError:
        return JsonResponse(
            {"error": "Couldn't load supported currencies right now."},
            status=503,
        )

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    if not isinstance(body, dict):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    pair, error_response = _validate_api_currencies(
        body.get("from"),
        body.get("to"),
        supported,
    )
    if error_response:
        return error_response
    from_currency, to_currency = pair

    amount, error_response = _parse_convert_amount(body.get("amount"))
    if error_response:
        return error_response

    try:
        rate_result = get_rate(from_currency, to_currency)
        result = convert(amount, from_currency, to_currency)
    except CurrencyConversionError:
        return JsonResponse(
            {"error": "Couldn't convert right now."},
            status=503,
        )

    remember_conversion_pair(
        request.session,
        ConversionPair(from_currency, to_currency),
    )

    payload = _rate_json(
        from_currency,
        to_currency,
        rate_result.rate,
        stale_date=rate_result.stale_date,
    )
    payload["converted_amount"] = format(_quantize_money(result), "f")
    return JsonResponse(payload)


@login_required
@require_GET
def currency_converter(request):
    try:
        supported = get_supported_currencies()
    except CurrencyConversionError:
        messages.error(
            request,
            "Couldn't load supported currencies right now. Try again in a moment.",
        )
        return render(
            request,
            "financetracker/converter.html",
            {
                "form": None,
                "rate_error": True,
            },
            status=200,
        )

    choices = _currency_choices(supported)
    url_from = request.GET.get("from") or None
    url_to = request.GET.get("to") or None
    amount_query = request.GET.get("amount", "")

    pair = resolve_conversion_pair(
        request.session,
        supported,
        url_from=url_from,
        url_to=url_to,
    )
    from_currency = pair.from_currency
    to_currency = pair.to_currency

    rate = None
    rates_stale_date = None
    rate_error = False

    try:
        rate_result = get_rate(from_currency, to_currency)
        rate = rate_result.rate
        rates_stale_date = rate_result.stale_date
    except CurrencyConversionError:
        rate_error = True

    initial = {
        "from_currency": from_currency,
        "to_currency": to_currency,
    }
    if amount_query:
        initial["amount"] = amount_query
    form = CurrencyConverterForm(initial=initial, currency_choices=choices)

    return render(
        request,
        "financetracker/converter.html",
        {
            "form": form,
            "from_currency": from_currency,
            "to_currency": to_currency,
            "rate": rate,
            "rate_error": rate_error,
            "rates_stale_date": rates_stale_date,
        },
    )
