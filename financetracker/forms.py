from django import forms

from .models import InvestmentEntry, Transaction


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
