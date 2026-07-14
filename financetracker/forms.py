from django import forms
from django.contrib.auth.forms import PasswordChangeForm, UserCreationForm
from django.contrib.auth.models import User

from .models import InvestmentEntry, Transaction, UserProfile


def build_currency_choices(supported_currencies):
    return sorted(
        ((code, f"{code} — {name}") for code, name in supported_currencies.items()),
        key=lambda item: item[0],
    )


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
        valid_codes = {choice[0] for choice in self.fields["default_currency"].choices if choice[0]}
        normalized = code.upper()
        if not normalized or normalized not in valid_codes:
            raise forms.ValidationError("Select a supported default currency.")
        return normalized


class DefaultCurrencyForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ["default_currency"]
        widgets = {
            "default_currency": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, currency_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["default_currency"].choices = list(currency_choices or [])

    def clean_default_currency(self):
        code = self.cleaned_data.get("default_currency", "")
        valid_codes = {choice[0] for choice in self.fields["default_currency"].choices}
        normalized = code.upper()
        if normalized not in valid_codes:
            raise forms.ValidationError("Select a supported default currency.")
        return normalized


class TransactionForm(forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ["type", "amount", "category", "description", "date"]
        widgets = {
            "type": forms.Select(attrs={"class": "form-select"}),
            "amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0.01", "placeholder": "0.00"}),
            "category": forms.Select(attrs={"class": "form-select"}),
            "description": forms.TextInput(attrs={"class": "form-control", "placeholder": "Optional note..."}),
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].empty_label = "— No category —"
        self.fields["category"].required = False


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
