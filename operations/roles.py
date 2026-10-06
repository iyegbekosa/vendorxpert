"""Staff roles. Each maps to a Django group with exactly these permissions.

Change the lists here and run ``python manage.py sync_roles`` (also run by
migration 0003) to apply them. Superusers have every permission.
"""

ROLES = {
    "Operations": [
        "userprofile.view_userprofile", "userprofile.suspend_user",
        "userprofile.view_vendorprofile", "userprofile.suspend_vendor",
        "userprofile.view_subscriptionhistory", "userprofile.view_vendorplan",
        "store.view_product", "store.moderate_product",
        "store.view_review", "store.moderate_review",
        "store.view_order", "store.view_payment", "store.recheck_payment", "store.view_category",
        "operations.view_supportticket", "operations.change_supportticket",
        "operations.view_ticketnote", "operations.add_ticketnote",
        "operations.view_auditlog", "operations.view_pickuplocation", "operations.view_platformsettings",
    ],
    "Finance": [
        "store.view_order", "store.refund_order", "store.view_payment", "store.recheck_payment",
        "userprofile.view_vendorprofile", "userprofile.view_vendorplan", "userprofile.change_vendorplan",
        "userprofile.view_subscriptionhistory",
        "operations.view_supportticket", "operations.change_supportticket",
        "operations.view_ticketnote", "operations.add_ticketnote", "operations.view_auditlog",
    ],
    "Moderator": [
        "store.view_product", "store.moderate_product", "store.view_review", "store.moderate_review",
        "store.view_category", "userprofile.view_vendorprofile",
        "operations.view_supportticket", "operations.change_supportticket",
        "operations.view_ticketnote", "operations.add_ticketnote",
    ],
    "Support": [
        "userprofile.view_userprofile", "userprofile.view_vendorprofile", "userprofile.view_subscriptionhistory",
        "store.view_order", "store.view_payment", "store.recheck_payment",
        "store.view_product", "store.view_review",
        "operations.view_supportticket", "operations.change_supportticket",
        "operations.view_ticketnote", "operations.add_ticketnote",
    ],
    "Content": [
        "store.view_category", "store.add_category", "store.change_category",
        "store.view_product", "store.feature_product",
        "operations.view_platformsettings", "operations.change_platformsettings",
        "operations.view_pickuplocation", "operations.add_pickuplocation", "operations.change_pickuplocation",
        "userprofile.view_vendorplan",
    ],
}


def sync_roles(group_model, permission_model):
    for role, permission_names in ROLES.items():
        group, _ = group_model.objects.get_or_create(name=role)
        permissions = []
        for name in permission_names:
            app_label, codename = name.split(".")
            permissions.append(
                permission_model.objects.get(content_type__app_label=app_label, codename=codename)
            )
        group.permissions.set(permissions)
