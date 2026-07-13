import json
from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.db.models import Q, Sum
from django.db.models.functions import TruncMonth
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from .models import Transaction, Category, InvestmentEntry
from .forms import (
    CurrencyConverterForm,
    CustomPasswordChangeForm,
    InvestmentEntryForm,
    ProfileForm,
    TransactionForm,
)
from .services.currency import (
    CurrencyConversionError,
    convert,
    get_rate,
    get_supported_currencies,
)


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.get_user())
            return redirect(request.GET.get("next", "dashboard"))
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
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, f"Welcome, {user.username}! Your account has been created.")
            return redirect("dashboard")
    else:
        form = UserCreationForm()
    return render(request, "financetracker/register.html", {"form": form})


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
    
    transactions = qs
    totals = Transaction.objects.filter(user=request.user).aggregate(
        total_income=Sum("amount", filter=Q(type="income")),
        total_expense=Sum("amount", filter=Q(type="expense")),
    )
    total_income = totals["total_income"] or Decimal("0")
    total_expense = totals["total_expense"] or Decimal("0")
    balance = total_income - total_expense

    return render(request, "financetracker/dashboard.html", {
        "transactions": transactions,
        "all_categories": all_categories,
        "selected_category": category_id,
        "q_query": q_query,
        "total_income": total_income,
        "total_expense": total_expense,
        "balance": balance,
    })


@login_required
def add_transaction(request):
    if request.method == "POST":
        form = TransactionForm(request.POST)
        if form.is_valid():
            t = form.save(commit=False)
            t.user = request.user
            t.save()
            messages.success(request, "Transaction added successfully.")
            return redirect("dashboard")
    else:
        form = TransactionForm(initial={"date": timezone.now().date()})
    return render(request, "financetracker/add_transaction.html", {
        "form": form,
        "title": "Add Transaction",
        "all_categories": Category.objects.all(),
    })


@login_required
def edit_transaction(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk, user=request.user)
    if request.method == "POST":
        form = TransactionForm(request.POST, instance=transaction)
        if form.is_valid():
            form.save()
            messages.success(request, "Transaction updated.")
            return redirect("dashboard")
    else:
        form = TransactionForm(instance=transaction)
    return render(request, "financetracker/add_transaction.html", {
        "form": form,
        "title": "Edit Transaction",
        "transaction": transaction,
        "all_categories": Category.objects.all(),
    })


@login_required
@require_POST
def delete_transaction(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk, user=request.user)
    transaction.delete()
    messages.success(request, "Transaction deleted.")
    return redirect("dashboard")


@login_required
def statistics(request):
    qs = Transaction.objects.filter(user=request.user)

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

    # Monthly chart filtered by date range
    monthly_qs = (
        qs_filtered
        .annotate(month=TruncMonth("date"))
        .values("month", "type")
        .annotate(total=Sum("amount"))
        .order_by("month")
    )

    months_map = {}
    for row in monthly_qs:
        label = row["month"].strftime("%b %Y")
        if label not in months_map:
            months_map[label] = {"income": 0, "expense": 0}
        months_map[label][row["type"]] = float(row["total"])

    month_labels   = list(months_map.keys())
    monthly_income  = [months_map[m]["income"]  for m in month_labels]
    monthly_expense = [months_map[m]["expense"] for m in month_labels]

    # Category breakdowns (filtered by date range)
    cat_expenses = (
        qs_filtered.filter(type="expense", category__isnull=False)
        .values("category__name")
        .annotate(total=Sum("amount"))
        .order_by("-total")
    )
    cat_labels = [r["category__name"] for r in cat_expenses]
    cat_values = [float(r["total"]) for r in cat_expenses]
    has_expense_categories = bool(cat_labels)

    cat_income = (
        qs_filtered.filter(type="income", category__isnull=False)
        .values("category__name")
        .annotate(total=Sum("amount"))
        .order_by("-total")
    )
    income_cat_labels = [r["category__name"] for r in cat_income]
    income_cat_values = [float(r["total"]) for r in cat_income]
    has_income_categories = bool(income_cat_labels)

    # Summary totals (filtered by date range)
    totals = qs_filtered.aggregate(
        total_income=Sum("amount", filter=Q(type="income")),
        total_expense=Sum("amount", filter=Q(type="expense")),
    )
    total_income  = float(totals["total_income"]  or 0)
    total_expense = float(totals["total_expense"] or 0)

    total_count   = qs_filtered.count()
    income_count  = qs_filtered.filter(type="income").count()
    expense_count = qs_filtered.filter(type="expense").count()

    return render(request, "financetracker/statistics.html", {
        "month_labels":       json.dumps(month_labels),
        "monthly_income":     json.dumps(monthly_income),
        "monthly_expense":    json.dumps(monthly_expense),
        "cat_labels":         json.dumps(cat_labels),
        "cat_values":         json.dumps(cat_values),
        "income_cat_labels":  json.dumps(income_cat_labels),
        "income_cat_values":  json.dumps(income_cat_values),
        "has_expense_categories": has_expense_categories,
        "has_income_categories": has_income_categories,
        "total_income":       total_income,
        "total_expense":      total_expense,
        "balance":            total_income - total_expense,
        "total_count":        total_count,
        "income_count":       income_count,
        "expense_count":      expense_count,
        "from_date":          from_date.isoformat(),
        "to_date":            to_date.isoformat(),
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
def settings_view(request):
    profile_form = ProfileForm(instance=request.user)
    password_form = CustomPasswordChangeForm(user=request.user)

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

    return render(request, "financetracker/settings.html", {
        "profile_form": profile_form,
        "password_form": password_form,
        "transaction_count": Transaction.objects.filter(user=request.user).count(),
        "investment_count": InvestmentEntry.objects.filter(user=request.user).count(),
    })


@login_required
@require_POST
def clear_all_transactions(request):
    count = Transaction.objects.filter(user=request.user).count()
    Transaction.objects.filter(user=request.user).delete()
    messages.success(request, f"Deleted all {count} transaction(s).")
    return redirect("settings")


@login_required
@require_POST
def clear_all_investments(request):
    count = InvestmentEntry.objects.filter(user=request.user).count()
    InvestmentEntry.objects.filter(user=request.user).delete()
    messages.success(request, f"Deleted all {count} investment entr{'y' if count == 1 else 'ies'}.")
    return redirect("settings")


DEFAULT_FROM_CURRENCY = "CZK"
DEFAULT_TO_CURRENCY = "EUR"
SESSION_FROM_KEY = "converter_from_currency"
SESSION_TO_KEY = "converter_to_currency"


def _currency_choices(supported):
    return sorted(
        ((code, f"{code} — {name}") for code, name in supported.items()),
        key=lambda x: x[0],
    )


def _resolve_currency(code, supported, session_value, default):
    if code:
        normalized = code.upper()
        if normalized in supported:
            return normalized
    if session_value and session_value in supported:
        return session_value
    return default


def _resolve_conversion_pair(request, supported, url_from=None, url_to=None):
    session_from = request.session.get(SESSION_FROM_KEY)
    session_to = request.session.get(SESSION_TO_KEY)
    from_currency = _resolve_currency(
        url_from,
        supported,
        session_from,
        DEFAULT_FROM_CURRENCY,
    )
    to_currency = _resolve_currency(
        url_to,
        supported,
        session_to,
        DEFAULT_TO_CURRENCY,
    )
    return from_currency, to_currency


def _quantize_money(value):
    return value.quantize(Decimal("0.01"))


def _quantize_rate(value):
    return value.quantize(Decimal("0.0001"))


def _rate_json(from_currency, to_currency, rate):
    return {
        "from": from_currency,
        "to": to_currency,
        "rate": format(_quantize_rate(rate), "f"),
    }


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
        rate = get_rate(from_currency, to_currency)
    except CurrencyConversionError:
        return JsonResponse(
            {"error": "Couldn't fetch the exchange rate right now."},
            status=503,
        )

    return JsonResponse(_rate_json(from_currency, to_currency, rate))


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
        rate = get_rate(from_currency, to_currency)
        result = convert(amount, from_currency, to_currency)
    except CurrencyConversionError:
        return JsonResponse(
            {"error": "Couldn't convert right now."},
            status=503,
        )

    request.session[SESSION_FROM_KEY] = from_currency
    request.session[SESSION_TO_KEY] = to_currency

    payload = _rate_json(from_currency, to_currency, rate)
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

    from_currency, to_currency = _resolve_conversion_pair(
        request,
        supported,
        url_from=url_from,
        url_to=url_to,
    )

    rate = None
    rate_error = False

    try:
        rate = get_rate(from_currency, to_currency)
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
        },
    )
