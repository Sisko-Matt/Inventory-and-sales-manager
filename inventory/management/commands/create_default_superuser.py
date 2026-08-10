import os

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from inventory.decorators import ADMIN_GROUP_NAME, SALES_STAFF_GROUP_NAME


class Command(BaseCommand):
    """
    Creates a superuser from environment variables, if one with that
    username doesn't already exist, and makes sure the Admin/Sales Staff
    groups exist. Safe to run on every deploy.

    Reads:
        DJANGO_SUPERUSER_USERNAME
        DJANGO_SUPERUSER_EMAIL
        DJANGO_SUPERUSER_PASSWORD
    """

    help = "Creates a superuser from DJANGO_SUPERUSER_* environment variables, if one doesn't already exist."

    def handle(self, *args, **options):
        User = get_user_model()

        admin_group, _ = Group.objects.get_or_create(name=ADMIN_GROUP_NAME)
        Group.objects.get_or_create(name=SALES_STAFF_GROUP_NAME)

        username = os.environ.get("DJANGO_SUPERUSER_USERNAME")
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")

        if not username or not password:
            self.stdout.write(
                self.style.WARNING(
                    "DJANGO_SUPERUSER_USERNAME or DJANGO_SUPERUSER_PASSWORD "
                    "not set - skipping superuser creation."
                )
            )
            return

        if User.objects.filter(username=username).exists():
            self.stdout.write(
                self.style.SUCCESS(f"Superuser '{username}' already exists - skipping.")
            )
            return

        user = User.objects.create_superuser(username=username, email=email, password=password)
        user.groups.add(admin_group)
        self.stdout.write(
            self.style.SUCCESS(f"Superuser '{username}' created and added to '{ADMIN_GROUP_NAME}'.")
        )
