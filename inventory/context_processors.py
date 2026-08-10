from .decorators import is_admin_user


def role_context(request):
    """
    Makes `is_admin` available in every template, purely so the navbar can
    show/hide Admin-only links. This is a UX convenience only - it has no
    bearing on actual access control, which is enforced server-side by the
    @admin_required decorator on the views themselves. Even if this
    context processor were removed entirely (or a Sales Staff user edited
    the page to reveal a hidden link), the underlying views would still
    reject them with a 403.
    """
    return {"is_admin": is_admin_user(request.user)}
