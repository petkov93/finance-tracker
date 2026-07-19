from django.core.management.base import BaseCommand

from financetracker.models import Category

DEFAULTS = [
    ("income", "Salary", "💼"),
    ("income", "Freelance", "💻"),
    ("income", "Other Income", "💰"),
    ("expense", "Food", "🍽️"),
    ("expense", "Food at Work", "🥪"),
    ("expense", "Health", "💊"),
    ("expense", "Cosmetics", "💄"),
    ("expense", "Transport", "🚗"),
    ("expense", "Rent", "🏠"),
    ("expense", "Entertainment", "🎬"),
    ("expense", "Utilities", "💡"),
    ("expense", "Clothes", "👕"),
]


class Command(BaseCommand):
    help = "Insert default categories only when the database has none."

    def handle(self, *args, **options):
        if Category.objects.exists():
            self.stdout.write("Categories already exist — leaving database unchanged.")
            return

        for type_, name, icon in DEFAULTS:
            Category.objects.create(name=name, icon=icon, type=type_)

        self.stdout.write(
            self.style.SUCCESS(f"Created {len(DEFAULTS)} default categories.")
        )
