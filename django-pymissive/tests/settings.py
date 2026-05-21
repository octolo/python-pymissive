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
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

if DEBUG:
    try:
        import debug_toolbar  # noqa: F401

        INSTALLED_APPS += ["debug_toolbar"]
        MIDDLEWARE += ["debug_toolbar.middleware.DebugToolbarMiddleware"]
        INTERNAL_IPS = ["127.0.0.1", "::1"]
        # Allow toolbar when using ngrok or other tunnels (client IP is not loopback).
        DEBUG_TOOLBAR_CONFIG = {
            "SHOW_TOOLBAR_CALLBACK": lambda request: DEBUG,
        }
    except ImportError:
        pass

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

LOCALE_PATHS = [BASE_DIR / "src" / "django_pymissive" / "locale"]

STATIC_URL = "/static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


ROOT_URLCONF = "tests.urls"
INSTALLED_APPS += [
    "virtualqueryset",
    "django_providerkit",
    "django_geoaddress",
    "phonenumber_field",
    "django_pymissive",
    "tests.fakeapp.apps.FakeappConfig",
]

# Address autocomplete view configuration
GEOADDRESS_PROVIDERVIEW = True
GEOADDRESS_PROVIDERVIEW_AUTH = True
GEOADDRESS_ADDRESSVIEW = True
GEOADDRESS_ADDRESSVIEW_AUTH = True

NGROK_PUBLIC_URL = os.getenv("NGROK_PUBLIC_URL")
if NGROK_PUBLIC_URL:
    from urllib.parse import urlparse
    url_data = urlparse(NGROK_PUBLIC_URL)
    MISSIVE_DOMAIN = url_data.netloc
    MISSIVE_SCHEME = url_data.scheme




try:
    from django_json_widget.widgets import JSONEditorWidget
    INSTALLED_APPS += [
        "django_json_widget",
    ]
    PYMISSIVE_JSON_WIDGET = "django_json_widget.widgets.JSONEditorWidget"
except ImportError:
    pass

try:
    import djrichtextfield
    INSTALLED_APPS += [
        "djrichtextfield",
    ]
    #PYMISSIVE_RICHTEXT_WIDGET = "djrichtextfield.widgets.RichTextWidget"
    DJRICHTEXTFIELD_CONFIG = {
        'js': [f'//cdn.tiny.cloud/1/{os.getenv("TINYMCE_API_KEY")}/tinymce/5/tinymce.min.js'],
        'init_template': 'djrichtextfield/init/tinymce.js',
        'settings': {
            'menubar': False,
            'plugins': 'link image',
            'toolbar': 'bold italic | link image | removeformat',
            'width': 700
        }
    }
except ImportError:
    pass


MISSIVE_AUTHENTICATED_ACKNOWLEDGEMENT = False
MISSIVE_SIGNED_ACKNOWLEDGEMENT = False
MISSIVE_QUALIFIED_ACKNOWLEDGEMENT = False

# PYMISSIVE_SAVE_UNTREATED_EVENTS = True  # Save events that could not be processed (default: False)
PYMISSIVE_ATTACHMENT_PATH_MAX_LENGTH = 4000
#PYMISSIVE_DRY_RUN = True
#PYMISSIVE_DISABLE_SEND = True
PYMISSIVE_DEFAULT_BODY_PROCESSORS = [
    # 1. Render Django template variables/tags ({{ var }}, {% if %}, …)
    "django_pymissive.processors.body.django_template.django_template_processor",
    # 2. Append a "Preview in browser" link at the end of the email body
    "django_pymissive.processors.body.add_preview_browser.add_preview_browser",
    # 3. Append the list of linked attachments at the end of the email body
    "django_pymissive.processors.body.add_attachments_linked.add_attachments_linked",
    # 4. Append the test signature (HTML for body_html, text for body_text)
    "tests.processors.add_signature",
]

# Default chain for the postal first_document PDF. The first entry renders
# the compiled HTML to PDF (WeasyPrint); subsequent entries receive the
# previous PDF bytes and may transform them. Here we stamp every page with
# a filigrane whose text is resolved at run-time from (most specific wins):
#   missive.additional_config["watermark"]
#   campaign.additional_config["watermark"]
#   settings.PYMISSIVE_WATERMARK
#   ["nom", "date", "draft"]   ← built-in fallback
# Font size auto-fits the page diagonal / number of lines unless pinned.
PYMISSIVE_DEFAULT_FIRST_DOCUMENT_PROCESSORS = [
    "django_pymissive.processors.pdf.weasyprint_renderer.weasyprint_renderer",
    [
        "django_pymissive.processors.pdf.watermark.watermark_processor",
        {"alpha": 0.18},
    ],
]

# Default watermark lines used by both first_document and attachment PDF
# processors when no per-missive / per-campaign override is configured.
PYMISSIVE_WATERMARK = ["nom", "date", "draft"]

# Default chain applied to every attachment's bytes right before they are
# handed to the provider. PDFs receive the same resolved filigrane; non-PDF
# files (DOCX, JPG, etc.) pass through untouched.
PYMISSIVE_DEFAULT_ATTACHMENT_PROCESSORS = [
    [
        "django_pymissive.processors.attachment.watermark.watermark_pdf_attachments",
        {"alpha": 0.18},
    ],
]

# Allowed file extensions per missive type. Set to None / unset to disable
# validation entirely. Use the special "default" key as fallback for missive
# types not listed explicitly. Empty list = attachments forbidden for that type.
PYMISSIVE_ALLOWED_ATTACHMENT_EXTENSIONS = {
    "default": [".pdf"],
    "email": [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".jpg", ".jpeg", ".png", ".tar"],
    "email_marketing": [".pdf", ".jpg", ".jpeg", ".png"],
    "ere": [".pdf"],
    "lre": [".pdf"],
    "lre_qualified": [".pdf"],
    "postal": [".pdf"],
    "postal_registered": [".pdf"],
    "postal_signature": [".pdf"],
    "sms": [],
    "rcs": [],
}
PROVIDERKIT_PROVIDERS_CONFIG = {
    "brevo": {
        "EMAIL_API_KEY": os.getenv("BREVO_EMAIL_API_KEY"),
        "SMS_API_KEY": os.getenv("BREVO_SMS_API_KEY"),
    },
    "scaleway": {
        "ACCESS_KEY": os.getenv("SCALEWAY_ACCESS_KEY"),
        "SECRET_ACCESS_KEY": os.getenv("SCALEWAY_SECRET_ACCESS_KEY"),
        "PROJECT_ID": os.getenv("SCALEWAY_PROJECT_ID"),
        "SNS_ACCESS_KEY": os.getenv("SCALEWAY_SNS_ACCESS_KEY"),
        "SNS_SECRET_KEY": os.getenv("SCALEWAY_SNS_SECRET_KEY"),
        "SUFFIX_SENDER_EMAIL": os.getenv("SCALEWAY_SUFFIX_SENDER_EMAIL"),
    },
    "maileva": {
        "USERNAME": os.getenv("MAILEVA_USERNAME"),
        "PASSWORD": os.getenv("MAILEVA_PASSWORD"),
        "CLIENTID": os.getenv("MAILEVA_CLIENTID"),
        "SECRET": os.getenv("MAILEVA_SECRET"),
        "SANDBOX": os.getenv("MAILEVA_SANDBOX", True),
    },
    "partner": {
        "SMS_API_KEY": os.getenv("PARTNER_SMS_API_KEY"),
    }
}
