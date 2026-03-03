# Missive

Monorepo contenant **python-missive** (bibliothèque Python pour l'envoi multi-canaux) et **django-missive** (intégration Django).

## Packages

### python-missive — `python-missive/`

Bibliothèque Python légère et indépendante du framework pour l'envoi de missives multi-canaux : emails, SMS, notifications push, courrier postal, etc. Basée sur ProviderKit.

- **15+ fournisseurs** : SendGrid, Mailgun, Twilio, La Poste, Telegram, FCM, APN, Slack, Teams, etc.
- **Architecture modulaire** : utilisable avec ou sans framework
- **Multi-canaux** : email, SMS, postal, messagerie, push

📁 Détails : [python-missive/README.md](python-missive/README.md) | Documentation : [python-missive/docs/](python-missive/docs/)

### django-missive — `django-missive/`

Intégration Django complète pour gérer l'envoi de missives multi-canaux. Interface d'administration, modèles, webhooks unifiés et suivi.

- **Interface d'administration Django** : gestion des missives avec validation et prévisualisation
- **Webhooks unifiés** : `/missive/webhook/{provider}/`
- **Modèle Recipient** : centralisation des coordonnées
- **Dépendance** : requiert python-missive

📁 Détails : [django-missive/README.md](django-missive/README.md)

## Structure du dépôt

```
missive/
├── python-missive/     # Bibliothèque core
├── django-missive/     # Intégration Django
└── README.md
```

## Développement

Chaque package dispose de son propre `service.py` :

```bash
# Dans python-missive/ ou django-missive/
./service.py dev install-dev
./service.py dev test
./service.py quality lint
```

## Licence

MIT
