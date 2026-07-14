import sys

from django.apps import AppConfig


class FinancetrackerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "financetracker"

    def ready(self):
        skip_commands = {
            "migrate",
            "makemigrations",
            "collectstatic",
            "shell",
            "createsuperuser",
            "seed_categories",
            "sync_exchange_rates",
            "check",
            "showmigrations",
            "test",
        }
        if any(cmd in sys.argv for cmd in skip_commands):
            return

        from django.db import connection
        from django.db.utils import OperationalError, ProgrammingError

        try:
            tables = connection.introspection.table_names()
        except (OperationalError, ProgrammingError):
            return

        if "financetracker_syncmetadata" not in tables:
            return

        from financetracker.services.currency import ensure_sync_if_stale

        ensure_sync_if_stale()
