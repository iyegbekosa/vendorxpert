from django.contrib.auth.management import create_permissions
from django.db import migrations


def create_roles(apps, schema_editor):
    # Custom permissions are normally created after migrations finish;
    # create them now so the roles can reference them.
    for app_config in apps.get_app_configs():
        app_config.models_module = True
        create_permissions(app_config, verbosity=0)
        app_config.models_module = None

    from operations.roles import sync_roles

    sync_roles(apps.get_model("auth", "Group"), apps.get_model("auth", "Permission"))


class Migration(migrations.Migration):
    dependencies = [
        ("operations", "0002_seed_defaults"),
        ("store", "0018_alter_order_options_alter_product_options_and_more"),
        ("userprofile", "0018_alter_userprofile_options_and_more"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]
    operations = [migrations.RunPython(create_roles, migrations.RunPython.noop)]
