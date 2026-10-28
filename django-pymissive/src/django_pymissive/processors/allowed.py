"""Allow-list callables for ``PYMISSIVE_RECIPIENT_ALLOWED``.

Dotted paths::

    "django_pymissive.processors.allowed.staff_emails"
    "django_pymissive.processors.allowed.admin_emails"
    "django_pymissive.processors.allowed.admin_staff_emails"
"""

from django.contrib.auth import get_user_model
from django.db.models import Q


def _emails(queryset) -> list[str]:
    emails = queryset.exclude(email="").values_list("email", flat=True)
    return [email.strip() for email in emails if email and str(email).strip()]


def staff_emails() -> list[str]:
    """Email addresses of active Django staff users."""
    return _emails(get_user_model().objects.filter(is_staff=True, is_active=True))


def admin_emails() -> list[str]:
    """Email addresses of active Django superusers."""
    return _emails(get_user_model().objects.filter(is_superuser=True, is_active=True))


def admin_staff_emails() -> list[str]:
    """Email addresses of active staff users and superusers."""
    users = get_user_model().objects.filter(is_active=True).filter(Q(is_staff=True) | Q(is_superuser=True))
    return _emails(users)
