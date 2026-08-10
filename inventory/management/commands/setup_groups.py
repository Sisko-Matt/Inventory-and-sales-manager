from django.core.management.base import BaseCommand

from inventory.decorators import ADMIN_GROUP_NAME, SALES_STAFF_GROUP_NAME
from django.contrib.auth.models import Group


class Command(BaseCommand):
    """
    Creates the two groups this project's role-based access control relies
    on: 'Admin' and 'Sales Staff'. Safe to run repeatedly - Group names are
    unique, so get_or_create() is a no-op on subsequent runs.

    Run this once after migrate, before assigning any user to a group
    (via the Django admin's User page, or the shell):

        python manage.py setup_groups
    """

    help = "Creates the 'Admin' and 'Sales Staff' groups used for role-based access control."

    def handle(self, *args, **options):
        admin_group, created_admin = Group.objects.get_or_create(name=ADMIN_GROUP_NAME)
        sales_group, created_sales = Group.objects.get_or_create(name=SALES_STAFF_GROUP_NAME)

        if created_admin:
            self.stdout.write(self.style.SUCCESS(f"Created group '{ADMIN_GROUP_NAME}'."))
        else:
            self.stdout.write(f"Group '{ADMIN_GROUP_NAME}' already exists - skipping.")

        if created_sales:
            self.stdout.write(self.style.SUCCESS(f"Created group '{SALES_STAFF_GROUP_NAME}'."))
        else:
            self.stdout.write(f"Group '{SALES_STAFF_GROUP_NAME}' already exists - skipping.")
