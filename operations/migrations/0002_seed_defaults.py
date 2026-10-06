from django.db import migrations

INITIAL_PICKUP_LOCATIONS = [
    ("admin", "Admin Block"),
    ("faculty", "Faculty Building"),
    ("tetfund", "TETFund Building"),
] + [(f"hall_{n}", f"Hall {n}") for n in range(1, 9)]


def seed(apps, schema_editor):
    PickupLocation = apps.get_model("operations", "PickupLocation")
    PlatformSettings = apps.get_model("operations", "PlatformSettings")
    for order, (code, label) in enumerate(INITIAL_PICKUP_LOCATIONS):
        PickupLocation.objects.get_or_create(code=code, defaults={"label": label, "sort_order": order})
    PlatformSettings.objects.get_or_create(pk=1)


class Migration(migrations.Migration):
    dependencies = [("operations", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
