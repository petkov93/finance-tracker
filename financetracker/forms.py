from django import forms
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User

from .models import InvestmentEntry, Transaction


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
