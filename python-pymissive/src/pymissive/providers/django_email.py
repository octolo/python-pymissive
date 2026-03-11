from .base import MissiveProviderBase


class DjangoEmailProvider(MissiveProviderBase):
    abstract = True
    name = "django_email"
    display_name = "Django Email Backend"
    description = "Lightweight email provider delegating to SMTP or local file delivery. Mimics Django's console/backend behaviour without importing Django."
