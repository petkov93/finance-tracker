import json
from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.db.models import Q, Sum
from django.db.models.functions import TruncMonth
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import Transaction, Category, InvestmentEntry
from .forms import TransactionForm, InvestmentEntryForm


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
    portfolio_value = total_invested + total_profit

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
