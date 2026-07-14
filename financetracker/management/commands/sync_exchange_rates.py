from django.core.management.base import BaseCommand

from financetracker.services.currency import CurrencyConversionError, sync_latest_rates


class Command(BaseCommand):
    help = "Bulk-fetch today's EUR-base exchange rates and supported currencies from Frankfurter."

    def handle(self, *args, **options):
        try:
            sync_latest_rates()
        except CurrencyConversionError as exc:
            self.stderr.write(self.style.ERROR(str(exc)))
            raise SystemExit(1) from exc

        self.stdout.write(self.style.SUCCESS("Exchange rates synced for today."))
