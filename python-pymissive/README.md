# python-missive

Bibliothèque Python légère et agnostique pour l'envoi de missives multi-canaux (emails, SMS, notifications push, courrier postal, etc.).

## Présentation

**python-missive** est une bibliothèque Python framework-agnostic qui fournit des providers unifiés pour l'envoi de messages multi-canaux. Elle sert de base à **django-missive** et peut être utilisée indépendamment dans n'importe quel projet Python.

### Fonctionnalités principales

- 🔌 **15+ providers intégrés** pour différents canaux de communication
- 📧 **Email** : SendGrid, Mailgun, SES, Brevo, SMTP, Django Email
- 📱 **SMS & Voix** : Twilio, Vonage, SMSPartner
- 💬 **Messaging** : Telegram, Signal, Messenger, Slack, Teams
- 📮 **Courrier postal & LRE** : La Poste, Maileva, AR24, Certeurope
- 🔔 **Notifications push** : FCM (Firebase), APN (Apple), In-App
- 🏗️ **Architecture modulaire** basée sur ProviderKit
- ✅ **Framework-agnostic** : utilisable avec ou sans framework
- 🎯 **Type hints complets** et documentation

## Installation

```bash
# Installation basique
pip install python-missive

# Avec dépendances pour providers spécifiques
pip install python-missive[email]      # Providers email
pip install python-missive[sms]        # SMS et vocal
pip install python-missive[messaging]  # Telegram, Signal, etc.
pip install python-missive[push]       # FCM, APN
pip install python-missive[postal]     # Courrier postal
pip install python-missive[all]        # Tous les providers
```

## Usage rapide

```python
from pymissive.providers.sendgrid import SendGridProvider

# Configurer le provider
provider = SendGridProvider(config={
    'SENDGRID_API_KEY': 'your-api-key'
})

# Envoyer un email
result = provider.send_email(
    from_email='sender@example.com',
    to_email='recipient@example.com',
    subject='Hello',
    body='<p>Message content</p>'
)
```

## Providers disponibles

### Email
- `DjangoEmailProvider` - Utilise le backend email Django
- `SMTPProvider` - SMTP générique
- `SendGridProvider` - SendGrid API
- `MailgunProvider` - Mailgun API
- `SESProvider` - Amazon SES
- `BrevoProvider` - Brevo (ex-Sendinblue)
- `ScalewayProvider` - Scaleway Transactional Email

### SMS & Voix
- `TwilioProvider` - Twilio SMS et appels vocaux
- `VonageProvider` - Vonage (ex-Nexmo)
- `SMSPartnerProvider` - SMSPartner

### Messaging
- `TelegramProvider` - Telegram Bot API
- `SignalProvider` - Signal Messenger
- `MessengerProvider` - Facebook Messenger
- `SlackProvider` - Slack
- `TeamsProvider` - Microsoft Teams

### Courrier postal & LRE
- `LaPosteProvider` - La Poste (courrier physique)
- `MailevaProvider` - Maileva
- `AR24Provider` - AR24 (LRE)
- `CerteuropeProvider` - Certeurope

### Notifications push
- `FCMProvider` - Firebase Cloud Messaging
- `APNProvider` - Apple Push Notification
- `InAppNotificationProvider` - Notifications in-app

## Architecture

La bibliothèque utilise **ProviderKit** pour la gestion des providers :

```python
from pymissive.providers import get_missive_providers

# Découvrir tous les providers disponibles
providers = get_missive_providers()

# Filtrer par type de service
email_providers = [p for p in providers if 'email' in p.services]
```

## Documentation

Pour plus de détails, consultez la documentation dans le dossier `docs/` :

- `docs/purpose.md` - Objectifs et architecture du projet
- `docs/structure.md` - Structure des modules et organisation
- `docs/development.md` - Guidelines de développement
- `docs/AI.md` - Contrat pour assistants IA

## Développement

```bash
# Créer un environnement virtuel
python service.py dev venv

# Installer en mode développement
python service.py dev install-dev

# Exécuter les tests
python service.py dev test

# Formater le code
python service.py dev format

# Lancer tous les checks qualité
python service.py quality check
```

## Licence

Ce projet est sous licence MIT. Voir le fichier `LICENSE` pour plus de détails.

