from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("financetracker", "0006_exchange_rates"),
    ]

    operations = [
        migrations.AddField(
            model_name="syncmetadata",
            name="sync_in_progress",
            field=models.BooleanField(default=False),
        ),
    ]
