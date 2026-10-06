from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

from operations.roles import ROLES, sync_roles


class Command(BaseCommand):
    help = "Create or update the staff role groups defined in operations/roles.py."

    def handle(self, *args, **options):
        sync_roles(Group, Permission)
        self.stdout.write(self.style.SUCCESS(f"Synced roles: {', '.join(ROLES)}"))
