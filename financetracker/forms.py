from decimal import Decimal

from django import forms
from django.contrib.auth.forms import PasswordChangeForm, UserCreationForm
from django.contrib.auth.models import User

from .models import BankAccount, InvestmentEntry, IOU, Transaction, UserProfile
from .services.bank_accounts import (
    assert_transaction_currency_matches_bank_account,
    bank_accounts_for_user,
    BankAccountError,
)
from .services.iou import selectable_categories

COMMON_CURRENCY_CODES = ("CZK", "USD", "EUR", "JPY", "GBP", "CNY")


def build_currency_choices(supported_currencies):
    normalized = {
        str(code).upper(): name for code, name in supported_currencies.items()
    }

    def label(code):
        return f"{code} — {normalized[code]}"

    all_choices = sorted(
        ((code, label(code)) for code in normalized),
        key=lambda item: item[0],
    )
    common_choices = [
        (code, label(code)) for code in COMMON_CURRENCY_CODES if code in normalized
    ]

    groups = []
    if common_choices:
        groups.append(("Common currencies", common_choices))
    groups.append(("All currencies", all_choices))
    return groups


def currency_choice_values(choices):
    """Yield option values from flat or optgroup ChoiceField choices."""
    for key, value in choices:
        if isinstance(value, (list, tuple)):
            for option_key, _option_label in value:
                if option_key:
                    yield option_key
        elif key:
            yield key


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["username", "email"]
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "Optional"}),
        }

    def clean_username(self):
        username = self.cleaned_data["username"]
        if User.objects.exclude(pk=self.instance.pk).filter(username=username).exists():
            raise forms.ValidationError("This username is already taken.")
        return username


class CustomPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({"class": "form-control"})


class RegistrationForm(UserCreationForm):
    default_currency = forms.ChoiceField(
        choices=[],
        required=True,
        label="Default currency",
        widget=forms.Select(
            attrs={
                "class": "form-select",
                "id": "id_default_currency",
            }
        ),
    )

    class Meta(UserCreationForm.Meta):
        fields = UserCreationForm.Meta.fields

    def __init__(self, *args, currency_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        choices = currency_choices or []
        self.fields["default_currency"].choices = [("", "— Select currency —"), *choices]
        for field_name in ("username", "password1", "password2"):
            self.fields[field_name].widget.attrs.update({"class": "form-control"})

    def clean_default_currency(self):
        code = self.cleaned_data.get("default_currency", "")
        valid_codes = set(currency_choice_values(self.fields["default_currency"].choices))
        normalized = code.upper()
        if not normalized or normalized not in valid_codes:
            raise forms.ValidationError("Select a supported default currency.")
        return normalized


class DefaultCurrencyForm(forms.ModelForm):
    default_currency = forms.ChoiceField(
        choices=[],
        required=True,
        label="Currency",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    class Meta:
        model = UserProfile
        fields = ["default_currency"]

    def __init__(self, *args, currency_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["default_currency"].choices = list(currency_choices or [])

    def clean_default_currency(self):
        code = self.cleaned_data.get("default_currency", "")
        valid_codes = set(currency_choice_values(self.fields["default_currency"].choices))
        normalized = code.upper()
        if normalized not in valid_codes:
            raise forms.ValidationError("Select a supported default currency.")
        return normalized


class TransactionForm(forms.ModelForm):
    currency = forms.ChoiceField(
        choices=[],
        required=True,
        label="Currency",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    bank_account = forms.ModelChoiceField(
        queryset=BankAccount.objects.none(),
        required=True,
        label="Bank account",
        empty_label=None,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    class Meta:
        model = Transaction
        fields = [
            "type",
            "amount",
            "currency",
            "bank_account",
            "category",
            "description",
            "date",
        ]
        widgets = {
            "type": forms.Select(attrs={"class": "form-select"}),
            "amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0.01", "placeholder": "0.00"}),
            "category": forms.Select(attrs={"class": "form-select"}),
            "description": forms.TextInput(attrs={"class": "form-control", "placeholder": "Optional note..."}),
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
        }

    def __init__(self, *args, user=None, currency_choices=None, default_currency=None, **kwargs):
        super().__init__(*args, **kwargs)
        choices = list(currency_choices or [])
        self.fields["currency"].choices = choices
        self.fields["category"].queryset = selectable_categories()
        self.fields["category"].empty_label = "— No category —"
        self.fields["category"].required = False
        if user is not None:
            accounts = bank_accounts_for_user(user)
            self.fields["bank_account"].queryset = accounts
            if not self.instance.pk:
                cash = accounts.filter(is_cash=True).first()
                if cash is not None:
                    self.fields["bank_account"].initial = cash.pk
        if not self.instance.pk and default_currency:
            self.fields["currency"].initial = default_currency

    def clean_currency(self):
        code = self.cleaned_data.get("currency", "")
        valid_codes = set(currency_choice_values(self.fields["currency"].choices))
        normalized = code.upper()
        if normalized not in valid_codes:
            raise forms.ValidationError("Select a supported currency.")
        return normalized

    def clean(self):
        cleaned = super().clean()
        currency = cleaned.get("currency")
        bank_account = cleaned.get("bank_account")
        if currency and bank_account is not None:
            try:
                assert_transaction_currency_matches_bank_account(
                    currency=currency,
                    bank_account=bank_account,
                )
            except BankAccountError as exc:
                raise forms.ValidationError(str(exc)) from exc
        return cleaned


class AssignBankAccountForm(forms.Form):
    bank_account = forms.ModelChoiceField(
        queryset=BankAccount.objects.none(),
        required=True,
        label="Bank account",
        empty_label=None,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, user_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = BankAccount.objects.all()
        if user_id is not None:
            queryset = queryset.filter(user_id=user_id)
        self.fields["bank_account"].queryset = queryset


class InvestmentEntryForm(forms.ModelForm):
    class Meta:
        model = InvestmentEntry
        fields = ["type", "amount", "description", "date"]
        widgets = {
            "type": forms.Select(attrs={"class": "form-select"}),
            "amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0.01", "placeholder": "0.00"}),
            "description": forms.TextInput(attrs={"class": "form-control", "placeholder": "Optional note..."}),
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
        }


class LendForm(forms.Form):
    counterparty_name = forms.CharField(
        max_length=255,
        label="Who did you lend to?",
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Name or nickname"},
        ),
    )
    amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01"),
        widget=forms.NumberInput(
            attrs={"class": "form-control", "step": "0.01", "min": "0.01", "placeholder": "0.00"},
        ),
    )
    currency = forms.ChoiceField(
        choices=[],
        required=True,
        label="Currency",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    due_date = forms.DateField(
        required=False,
        label="Due date",
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    date = forms.DateField(
        label="Transaction date",
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )

    def __init__(self, *args, currency_choices=None, default_currency=None, **kwargs):
        super().__init__(*args, **kwargs)
        choices = list(currency_choices or [])
        self.fields["currency"].choices = choices
        if default_currency and not self.is_bound:
            self.fields["currency"].initial = default_currency

    def clean_currency(self):
        code = self.cleaned_data.get("currency", "")
        valid_codes = set(currency_choice_values(self.fields["currency"].choices))
        normalized = code.upper()
        if normalized not in valid_codes:
            raise forms.ValidationError("Select a supported currency.")
        return normalized


class BorrowForm(LendForm):
    counterparty_name = forms.CharField(
        max_length=255,
        label="Who did you borrow from?",
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Name or nickname"},
        ),
    )


class RepayForm(forms.Form):
    amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01"),
        widget=forms.NumberInput(
            attrs={"class": "form-control", "step": "0.01", "min": "0.01", "placeholder": "0.00"},
        ),
    )
    date = forms.DateField(
        label="Transaction date",
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )

    def __init__(self, *args, max_amount=None, currency=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_amount = max_amount
        self.currency = currency

    def clean_amount(self):
        amount = self.cleaned_data.get("amount")
        if amount is None or self.max_amount is None:
            return amount
        if amount > self.max_amount:
            raise forms.ValidationError(
                f"Amount cannot exceed remaining balance "
                f"({self.max_amount:.2f} {self.currency})."
            )
        return amount


class IOUMetadataForm(forms.Form):
    counterparty_name = forms.CharField(
        max_length=255,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Name or nickname"},
        ),
    )
    due_date = forms.DateField(
        required=False,
        label="Due date",
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )


class CurrencyConverterForm(forms.Form):
    amount = forms.DecimalField(
        required=False,
        max_digits=12,
        decimal_places=2,
        widget=forms.NumberInput(
            attrs={
                "class": "form-control",
                "step": "0.01",
                "min": "0.01",
                "placeholder": "0.00",
                "id": "converter-amount",
            }
        ),
    )
    from_currency = forms.ChoiceField(
        widget=forms.Select(attrs={"class": "form-select", "id": "converter-from"}),
    )
    to_currency = forms.ChoiceField(
        widget=forms.Select(attrs={"class": "form-select", "id": "converter-to"}),
    )

    def __init__(self, *args, currency_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        choices = currency_choices or []
        self.fields["from_currency"].choices = choices
        self.fields["to_currency"].choices = choices

    def clean_amount(self):
        raw = self.data.get("amount", "")
        if raw == "":
            raise forms.ValidationError("Enter an amount to convert.")
        amount = self.cleaned_data.get("amount")
        if amount is None:
            return amount
        if amount <= 0:
            raise forms.ValidationError("Amount must be greater than zero.")
        return amount
