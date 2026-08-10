from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

ADMIN_GROUP_NAME = "Admin"
SALES_STAFF_GROUP_NAME = "Sales Staff"


def is_admin_user(user):
    """A superuser always counts as Admin too, so the account created by
    createsuperuser/create_default_superuser works without extra setup."""
    return user.is_authenticated and (
        user.is_superuser or user.groups.filter(name=ADMIN_GROUP_NAME).exists()
    )


def admin_required(view_func):
    """
    Restricts a view to users in the 'Admin' group (or superusers).

    This is deliberately a server-side check that raises PermissionDenied
    (a real 403 response), not a template-level "hide the link" - so a
    Sales Staff user who navigates straight to a restricted URL is blocked
    regardless of what the navbar shows them. This is what the spec means
    by "do not rely only on hiding menu items."
    """

    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if is_admin_user(request.user):
            return view_func(request, *args, **kwargs)
        raise PermissionDenied(
            "This page is restricted to Admin users."
        )

    return wrapper
