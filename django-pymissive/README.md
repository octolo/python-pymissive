# Django Missive

🚀 Une bibliothèque Django complète pour gérer l'envoi de **missives multi-canaux** : emails, SMS, WhatsApp, courrier postal, et notifications in-app.

## ✨ Features

### Fonctionnalités principales

- 📧 **Multi-canaux** : 14 types supportés (Email, SMS, WhatsApp, Telegram, Signal, Messenger, RCS, Courrier postal, LRE, Appels vocaux, Notifications push, Slack, Teams)
- 🔌 **15+ providers intégrés** : SendGrid, Mailgun, Twilio, La Poste, Telegram, FCM, APN, Slack, Teams, etc.
- 📎 **Pièces jointes flexibles** : Fichiers locaux OU URLs externes (S3, Google Drive)
- 🔔 **Webhooks unifiés** : Un seul endpoint `/missive/webhook/{provider}/`
- 📊 **Tracking complet** : Historique, statuts, événements
- 🎯 **Modèle Recipient** : Centralisation des coordonnées (email, téléphone, adresse)
- 🔍 **Validation intégrée** : Tests de risque d'échec avant envoi
- 👨‍💼 **Admin Django complet** : Interface de gestion avec actions de validation
- 🔗 **GenericForeignKey** : Lien flexible avec vos modèles métier
- 📝 **Templates réutilisables** : Créez des templates de missives
- 📊 **Monitoring avancé** : Services, crédits, SLA et health check pour chaque provider
- 🔄 **Fallback automatique** : Bascule vers un provider de secours en cas de panne

### Architecture technique

- ✅ Compatible Django 3.2+ et Python 3.9+
- ✅ Structure modulaire par mixins (providers/base/)
- ✅ Tests unitaires complets (8/8 ✅)
- ✅ Documentation exhaustive (16 fichiers .md)
- ✅ CI/CD avec GitHub Actions
- ✅ Type hints et mypy
- ✅ Code formaté avec Black + isort

## Installation

### 🔧 Mode développement (projet local)

```bash
# Core uniquement (Django + validation)
pip install -r requirements.txt

# Développement (tests, linters)
pip install -r requirements-dev.txt

# Tous les providers
pip install -r requirements-all.txt
```

### 📦 Mode production (futur - après publication PyPI)

```bash
# Installation de base
pip install django-missive

# Avec providers spécifiques
pip install django-missive[email]        # Email (SendGrid, Mailgun, SES)
pip install django-missive[sms]          # SMS & Vocal (Twilio, Vonage)
pip install django-missive[messaging]    # Telegram, Signal, Messenger
pip install django-missive[push]         # Notifications push (FCM, APN)
pip install django-missive[professional] # Slack, Teams
pip install django-missive[postal]       # Courrier, LRE
pip install django-missive[all]          # Tous les providers
```

## Quick Start

1. Add `django_pymissive` to your `INSTALLED_APPS` in `settings.py`:

```python
INSTALLED_APPS = [
    ...
    'django_pymissive',
]
```

2. Run migrations:

```bash
python manage.py migrate django_pymissive
```

3. Include the URLconf in your project `urls.py`:

```python
from django.urls import path, include

urlpatterns = [
    ...
    path('missive/', include('django_pymissive.urls')),  # Webhooks
]
```

This will create the following URLs:
- `/missive/webhook/{provider}/` - Webhook unifié pour tous les providers

4. Configure providers in `settings.py`:

```python
# Configuration Django Missive
MISSIVE_PROVIDERS = {
    # Providers par type de missive (utilise python-missive)
    'EMAIL': {
        'backend': 'pymissive.providers.sendgrid.SendGridProvider',
        'config': {
            'SENDGRID_API_KEY': os.getenv('SENDGRID_API_KEY'),
        }
    },
    'SMS': {
        'backend': 'pymissive.providers.twilio.TwilioProvider',
        'config': {
            'TWILIO_ACCOUNT_SID': os.getenv('TWILIO_ACCOUNT_SID'),
            'TWILIO_AUTH_TOKEN': os.getenv('TWILIO_AUTH_TOKEN'),
            'TWILIO_PHONE_NUMBER': '+33123456789',
        }
    },
    'POSTAL': {
        'backend': 'pymissive.providers.laposte.LaPosteProvider',
        'config': {
            'LAPOSTE_API_KEY': os.getenv('LAPOSTE_API_KEY'),
        }
    },
}

# Email par défaut
DEFAULT_FROM_EMAIL = 'noreply@example.com'
```

## 🚀 Usage rapide

### Envoyer un email

```python
from django_pymissive.models import Missive, MissiveType, MissiveEventType

# Créer une missive email
missive = Missive.objects.create(
    sender=request.user,
    missive_type=MissiveType.EMAIL,
    recipient_email="client@example.com",
    subject="Commande confirmée",
    body="<p>Votre commande #123 est confirmée</p>",
    body_text="Votre commande #123 est confirmée",
    status=MissiveEventType.PENDING,
)

# L'envoi peut être géré via des tâches asynchrones ou manuellement
```

### Utiliser le modèle pour créer des missives

```python
from django_pymissive.models import Missive, MissiveType, MissiveEventType

# Créer un destinataire avec toutes ses coordonnées
missive = Missive.objects.create(
    sender=request.user,
    missive_type=MissiveType.EMAIL,
    recipient_first_name="Jean",
    recipient_last_name="Dupont",
    recipient_email="jean@acme.com",
    recipient_phone="+33600000000",
    recipient_address_line1="123 Rue de la Paix",
    recipient_postal_code="75001",
    recipient_city="Paris",
    recipient_country="FR",
    subject="Bienvenue",
    body="<p>Bonjour Jean, bienvenue!</p>",
    status=MissiveEventType.PENDING,
)

# Créer un SMS avec les mêmes coordonnées
sms = Missive.objects.create(
    sender=request.user,
    missive_type=MissiveType.SMS,
    recipient_phone="+33600000000",
    body="Votre code de vérification: 123456",
    status=MissiveEventType.PENDING,
)
```

### Monitoring des providers (via python-missive)

```python
from pymissive.providers.sendgrid import SendGridProvider

# Configurer et vérifier le provider
provider = SendGridProvider(config={
    'SENDGRID_API_KEY': 'your-api-key'
})

# Vérifier la configuration
is_configured = provider.is_configured()
print(f"Provider configuré: {is_configured}")

# Envoyer un email de test
result = provider.send_email(
    from_email='sender@example.com',
    to_email='recipient@example.com',
    subject='Test',
    body='<p>Test message</p>'
)
```

### Valider et envoyer

```python
from django_pymissive.models import Missive, MissiveEventType

# Récupérer une missive
missive = Missive.objects.get(id=123)

# Vérifier qu'elle est prête à être envoyée
if missive.status == MissiveEventType.PENDING:
    # Marquer comme envoyée (l'envoi réel se fait via le provider configuré)
    missive.status = MissiveEventType.SENT
    missive.save()
```

## Development

### Quick Start

This project includes `service.py` - a cross-platform development tool that works on **all operating systems**.

```bash
# Setup development environment
python service.py dev install-dev

# Run tests
python service.py dev test

# Format code
python service.py dev format

# Build package
python service.py dev build
```

**Linux/macOS users** can make it executable:
```bash
chmod +x service.py
./service.py dev install-dev
./service.py dev test
```

### Available Commands

**Development:**
- `python service.py dev venv` - Create virtual environment
- `python service.py dev install` - Install in production mode
- `python service.py dev install-dev` - Install in development mode

**Testing:**
- `python service.py dev test` - Run tests with pytest
- `python service.py dev test-verbose` - Run tests with verbose output
- `python service.py dev coverage` - Run tests with coverage report

**Code Quality:**
- `python service.py quality lint` - Run linters (flake8, mypy)
- `python service.py quality format` - Format code (black, isort)
- `python service.py quality check` - Run all checks (lint + format check)

**Building:**
- `python service.py dev build` - Build wheel and source distribution
- `python service.py dev clean` - Remove all build artifacts
- `python service.py dev clean-test` - Remove test artifacts (htmlcov, .coverage, etc.)

**Publishing:**
- `python service.py dev upload-test` - Upload to TestPyPI
- `python service.py dev upload` - Upload to PyPI
- `python service.py dev release` - Full release workflow

**Utilities:**
- `python service.py dev show-version` - Show current version
- `python service.py dev venv-clean` - Recreate virtual environment

Run `python service.py dev help` to see all available commands.

### Django Development Server

Test the library with a Django development server:

```bash
# Run migrations and create superuser (admin/admin)
python service.py dev migrate

# Start development server
python service.py dev runserver
```

Access the admin interface at http://127.0.0.1:8000/admin/ (login: admin/admin)

See [docs/development.md](docs/development.md) for detailed development guide (if available).

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Changelog

### 0.1.0 (Initial Release)

- Initial release
- Basic functionality

## Support

If you encounter any issues or have questions, please file an issue on the [GitHub issue tracker](https://github.com/yourusername/django-missive/issues).

