"""Django settings for testing django-missive."""

import os
import sys
from pathlib import Path

# Add src to Python path for development
BASE_DIR = Path(__file__).resolve().parent.parent
src_path = BASE_DIR / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

SECRET_KEY = os.getenv("SECRET_KEY", "test-secret-key-for-django-missive")
DEBUG = True
ALLOWED_HOSTS = ["*", ".ngrok.io", ".ngrok-free.app"]

INSTALLED_APPS = [
    "django_boosted",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(BASE_DIR, "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": "db.sqlite3",
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


ROOT_URLCONF = "tests.urls"
INSTALLED_APPS += [
    "virtualqueryset",
    "django_providerkit",
    "django_geoaddress",
    "phonenumber_field",
    "django_pymissive",
]

# Address autocomplete view configuration
GEOADDRESS_PROVIDERVIEW = True
GEOADDRESS_PROVIDERVIEW_AUTH = True
GEOADDRESS_ADDRESSVIEW = True
GEOADDRESS_ADDRESSVIEW_AUTH = True

NGROK_PUBLIC_URL = os.getenv("NGROK_PUBLIC_URL")


SCALEWAY_SNS_ACCESS_KEY = "PfJEDJrCiff1FKzClXnF"
SCALEWAY_SNS_SECRET_KEY = (
    "fckt8EDSXXG5VOrQpWKDlwCtTuHleANDdE7kYIfWwXHcl70UEbWjmC5Q6QQ7q2l1"
)
SNS_ACCESS_KEY = "PfJEDJrCiff1FKzClXnF"
SNS_SECRET_KEY = "fckt8EDSXXG5VOrQpWKDlwCtTuHleANDdE7kYIfWwXHcl70UEbWjmC5Q6QQ7q2l1"

MISSIVE_SCALEWAY_SNS_ACCESS_KEY = "PfJEDJrCiff1FKzClXnF"
MISSIVE_SCALEWAY_SNS_SECRET_KEY = (
    "fckt8EDSXXG5VOrQpWKDlwCtTuHleANDdE7kYIfWwXHcl70UEbWjmC5Q6QQ7q2l1"
)
