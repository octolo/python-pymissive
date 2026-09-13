# Revue globale — monorepo `python-pymissive`

Date : 13/09/2026 · Périmètre : `python-pymissive` (5 093 l.) + `django-pymissive` (25 518 l.)
Méthode : lecture intégrale des deux paquets, exécution de la suite de tests, vérification manuelle
de tous les points P0/P1 (chaque ligne citée a été relue).

Non déployable en production en l'état : 3 problèmes P0 ouverts.
Ce document ne liste que ce qui reste à faire ; les points corrigés en sont retirés au fur et à mesure.

---

## P0 — bloquant

### 1. Le webhook accepte les événements de n'importe qui

`views/webhook.py:16-39` : `csrf_exempt`, `post()` **et** `get()` passent `request.body` à
`handle_events` sans aucune vérification. Aucune signature HMAC, aucun secret partagé, aucune
fenêtre anti-replay, aucun rate limit. Et la vérification est *structurellement impossible*
aujourd'hui : `events.py:117-119` ne transmet que `payload=events`, jamais les en-têtes, et les
providers se contentent d'un `json.loads` (`pymissive/providers/brevo.py:543-548`,
`maileva.py:1126-1130`).

Conséquence : un `POST {"external_id": "...", "event": "delivered"}` suffit à marquer une LRE comme
distribuée. C'est l'historique de distribution dont cette librairie est censée être la source
d'autorité.

### 2. Scaleway : SSRF sur le webhook, et fuite des secrets SNS par défaut

- `providers/scaleway.py:396-400` : `SubscribeURL` est pris tel quel dans le corps du webhook
  (non signé, cf. P0-1) et passé à `requests.get(subscription_url, timeout=30)`. SSRF lisible
  depuis le réseau interne, et confirmation automatique d'abonnements SNS arbitraires.
- `providers/scaleway.py:458-480` : **afficher le secret une fois est volontaire et légitime** —
  Scaleway ne renvoie la `secret_key` qu'à la création, il faut donc la récupérer pour la reporter
  dans la configuration. La branche `print` n'est donc pas un défaut. Deux points restent à traiter :
  - **Le défaut n'affiche pas, il écrit un fichier.** Sans `SCALEWAY_SNS_SAVE_METHOD`, la branche
    `else` **append** `SNS_SECRET_KEY = ...` en clair dans `sns_credentials_<project_id>.txt`, dans
    le CWD du process et sans mode `0600`. Or ce chemin n'est pas réservé à un opérateur en
    terminal : `MissiveWebhook.save()` (`models/webhook.py:116-119`) → `create_webhook_email`
    (`scaleway.py:373-375`) → `sns_client_email` → `sns_client` → `create_sns_credentials`
    (`scaleway.py:515-516`) se déclenche depuis l'admin Django dès que `SNS_ACCESS_KEY` /
    `SNS_SECRET_KEY` ne sont pas déjà configurés. Le fichier atterrit alors dans le répertoire de
    travail de gunicorn. `print` ferait un meilleur défaut, le fichier devenant opt-in avec un
    chemin explicite.
  - **La branche `logger` est cassée.** `logger.info("SNS_ACCESS_KEY =", access_key)` n'a pas de
    `%s`, donc le formatage lève et l'enregistrement est perdu. Vérifié : rien n'est journalisé,
    mais `logging` écrit sur stderr un « Logging error » contenant `Arguments: ('SCW...',)` — le
    secret sort quand même, dans une traceback, au pire endroit possible.

### 3. Chemins de double envoi réels

Quatre défauts indépendants qui mènent tous à envoyer deux fois :

- **`retrieve_missive()` peut remettre une missive envoyée à `DRAFT`.** `managers/event.py:19` ignore
  volontairement les événements sans destinataire, or l'événement `REQUEST` écrit par `send_missive`
  n'en a pas (`models/missive.py:1339-1344`). Compteurs `(0,0,0)` → `status_from_event_counts`
  renvoie `DRAFT` (`models/choices.py:219-220`) → persisté (`models/missive.py:1461-1463`). Le
  bouton Envoyer réapparaît et `pending_send_queryset()` reprend la ligne au run suivant. Déclenché
  par un simple clic sur « Statut ». Aucun test n'assère le statut post-retrieve.
- **`set_status()` annule silencieusement un `CANCELLED`** : aucune garde d'état terminal, et
  `status_from_event_counts` ne peut jamais renvoyer `CANCELLED` (`models/choices.py:216-231`).
- **`PROCESSING` est un cul-de-sac** : absent de `PENDING_STATUSES` comme de `ERROR_STATUSES`
  (`models/choices.py:80-88`), donc plus rien ne reprend ces lignes. Symétriquement `ended_at` n'est
  posé que dans un `finally` (`models/scheduler.py:502-503`) : un SIGKILL laisse `is_running` vrai
  pour toujours et `start_campaign` lève « déjà en cours » définitivement. Aucun bail, heartbeat ou
  timeout.
- **Appel provider dans une transaction ouverte** : `resend_missive` est `@transaction.atomic`
  (`models/missive.py:1065`) et envoie ligne 1090. Un échec après l'envoi rollback l'`external_id`
  et l'événement `REQUEST` alors que le courrier est parti.

---

## P1 — à corriger rapidement

| # | Problème | Emplacement |
|---|---|---|
| 4 | **XSS stockée dans l'admin** : `mark_safe(f'<a href="{url}">{label}</a>')` où `label` vient de `str(content_object)` d'objets métier arbitraires. Fix : `format_html`. | `admin/related_object.py:34` |
| 5 | **SSRF lisible** : `url = request.GET.get("url")` → `obj.download_proof(url=url)`, sans allowlist, en GET, et les octets sont renvoyés à l'appelant. | `admin/missive.py:796-813` |
| 6 | **`has_change_permission` renvoie `True` inconditionnellement** et n'appelle jamais `super()`. Tout compte `is_staff` sans aucune permission liste, ouvre et modifie toutes les missives — et déclenche `send_missive`. « Staff » = « peut dépenser de l'argent ». | `admin/missive.py:568-573` |
| 7 | **`PreviewView` est le seul endpoint de preview sans authentification** (`class PreviewView(DetailView)` nu, vs `staff_member_required` sur ses 4 voisins) — et ce GET anonyme **écrit en base** : `ensure_first_document()` supprime et régénère le PDF via WeasyPrint. Les docstrings du modèle l'appellent « Staff preview URL ». | `views/preview.py:346`, `:438-439` |
| 8 | **Zéro index, zéro contrainte en 20 migrations.** Aucun `AddIndex`/`AddConstraint`/`unique_together`. Manquent surtout : `Missive.external_id` (clé de jointure de *tous* les webhooks, retrieves et billings — ni indexée ni unique), `Missive.status`, `thread_type`, et `(content_type, object_id)` sur les FK génériques, filtré par une sous-requête corrélée par ligne annotée. | `migrations/`, `models/missive.py:258-265` |
| 9 | **Collisions d'`external_id` non gérées** : `events.py:107` et `billings.py:58` font `.get(external_id=...)` en n'attrapant que `DoesNotExist`. En dry-run l'id dérive du `thread_id` réutilisé par les resends → `MultipleObjectsReturned` garanti. | `models/missive.py:1371`, `:1086` |
| 10 | **`__init_subclass__` efface ce qu'il est censé gérer** : il s'exécute *après* le corps de la sous-classe, donc `cls.brands = []` écrase la déclaration. `get_brands()` renvoie `[]` pour tous les providers. Pire, `attachments` est une liste de classe partagée entre instances → fuite d'une missive à la suivante. La garde `if not hasattr(self, "attachments")` (`brevo.py:96`) est du code mort. | `providers/base/branded.py:4-6`, `base/attachments.py:4-6` |
| 11 | **Un `post_save` déclenche un appel provider synchrone par événement** : fanout = 1 événement par destinataire, donc un webhook sur 50 destinataires = 50 appels de facturation dans la requête. Combiné à P0-1, le webhook est un amplificateur non authentifié contre votre quota provider. | `signals.py:24-30` |
| 12 | **Le webhook répond toujours 200**, donc tout échec devient une perte définitive : le provider ne réessaie jamais. Un webhook arrivant avant le commit de l'`external_id` est perdu (sauf `PYMISSIVE_SAVE_UNTREATED_EVENTS`, `False` par défaut). Aucun test HTTP sur cette vue. | `views/webhook.py:35-39`, `events.py:105-131` |
| 13 | **`get_event_counts` charge toutes les lignes d'événements en Python**, JSON `trace`/`metadata` compris, juste pour lire `.event`. Exécuté une fois par destinataire *et* une fois par missive à chaque événement. | `managers/event.py:19-29` |
| 14 | **Aucun lint, format ou typecheck** : ni `.pre-commit-config.yaml`, ni ruff/flake8/black/isort/mypy, nulle part — alors que le README annonce Black, isort et mypy. | — |
| 15 | **4 `search_fields` lèvent `FieldError`** (vérifié par exécution) : la barre de recherche renvoie un 500. `missive__recipients__*` (`recipients` est une property), `campaign__name` (×2, le champ est `subject`), `missive__recipient_name`. | `admin/related_object.py:66-69`, `:118`, `admin/attachment.py:33-34` |
| 16 | **Documentation très décalée du code.** Sur les 9 providers annoncés en tête de README, **2 existent** (Slack, Teams). SendGrid, Mailgun, Twilio, Telegram, FCM, APN sont des stubs de 8 lignes dans `providers/todo/` qui **ne s'importent même pas** (`from .base import ...` alors qu'il n'y a pas de `todo/base.py`). Le premier exemple de code de chaque README est donc inexécutable. S'y ajoutent : 13 extras pip inexistants, mauvais noms d'install (`pip install django-missive`), l'URL webhook documentée qui 404 (il faut 2 segments), les 3 `requirements*.txt` inexistants, et le `service.py` documenté sur ~45 lignes qui n'a jamais été écrit. | `README.md:11`, `python-pymissive/README.md:39`, `django-pymissive/README.md:24-30` |

---

## P2 — dette notable

**Cœur `pymissive`**

- Aucun provider ne vérifie de signature webhook (`maileva.py:1126`, `brevo.py:543`, `scaleway.py:402`,
  `partner.py:167`). Aucun `hmac`/`hashlib` dans tout le paquet.
- `get_normalize_event` plante pour Slack/Teams/Discord : la base déclare `events_association = None`
  et cette méthode l'appelle sans garde, contrairement à `get_events_association()` une ligne plus haut
  (`base/__init__.py:105-107`).
- 3 des 4 commandes CLI lisent une clé que `clicommands` ne renvoie jamais (`parsed.get("command")` au
  lieu de `parsed.get("args")`) : `attachment add/delete` et `recipient format` sont inatteignables, et
  `--dir`/`--json` sont ignorés (`commands/attachment.py:29`, `billing.py:32`, `recipient.py:24`).
  `missive.py:70` fait juste — d'où l'incohérence.
- `is_acknowledgement_of_receipt` est un prédicat à effet de bord qui cache `ack_level`
  (`maileva.py:578-581`), et ce flag pilote quelle API Maileva est appelée (`v2` vs `v4`, `mail` vs
  `registered_mail`). Si providerkit réutilise l'instance, la 1re missive route les suivantes vers le
  mauvais produit — écart de facturation *et* de valeur juridique.
- Un envoi Maileva réussi est étiqueté en erreur : après `raise_for_status()`, `"request" if
  status_code == 200 else "error"` — un `201`/`202` normal devient `"error"` (`maileva.py:723-728`).
- `"None None"` imprimé sur les enveloppes : `f"{address.get('postal_code')} {address.get('city')}"`
  envoyé comme `address_line_6` (`maileva.py:486`, `:611`).
- `delete_blocked_emails` réabonne tous les destinataires **avant chaque envoi**, ressuscitant les hard
  bounces et les désinscrits, sous `contextlib.suppress(Exception)` avec `return True` en dur
  (`brevo.py:306-315`). Problème de réputation de délivrabilité et de consentement RGPD.
- Numéro de téléphone personnel codé en dur comme expéditeur WhatsApp : `sender = "+33614397083"`
  (`brevo.py:668`).
- Timeouts absents sur tous les appels `urllib` (`slack.py:60`, `teams.py:87`, `brevo.py:485`, `:600`)
  et sur tout `partner.py` — en chemin de requête synchrone, un envoi bloqué immobilise le worker.
- `partner.py:148` envoie l'`apiKey` en query string (logs d'accès, proxies, `Referer`).
- `get_config_by_support` ne peut pas fonctionner : `getattr(globals(), ...)` sur un `dict`
  (`config/__init__.py:255-260`). Sans appelant, donc jamais remarqué.
- Les deux offsets d'adresse LRE sont byte-identiques, donc le branchement est un no-op alors que
  `models/missive.py:844` s'en sert pour générer le CSS de fenêtre (`maileva.py:14-24`).
- `access_token` est un `cached_property` : un worker long-lived garde un token Keycloak périmé et
  tous les appels suivants 401 sans retry (`maileva.py:372-385`).
- ~15 méthodes annotées `-> bool` renvoient des dicts, listes, bytes ou str (`maileva.py`). Les
  annotations sont activement trompeuses, pas simplement absentes.
- Les 5 mixins `email`/`postal`/`sms`/`notification`/`voice_call` sont vides (2 lignes, une docstring) :
  aucun contrat n'est exprimé ni vérifiable, et les signatures `send_*` dérivent librement d'un
  provider à l'autre.
- Réponses API complètes embarquées dans les messages d'exception (`maileva.py:393-403`) : noms et
  adresses postales finissent dans les tracebacks, Sentry et les mails d'erreur Django.
- `helpers.py` est un fichier de 0 octet, livré dans la wheel.

**Couche données Django**

- `Missive.objects` force un GROUP BY sur 5 jointures à **chaque** requête, `body_rich`/`body_text`
  inclus dans le GROUP BY (~14 ko de SQL). Comme les managers de relation inverse en héritent, c'est
  aussi le coût de `campaign.to_missive` et `scheduler.to_missive`. Le manager campagne documente
  précisément pourquoi c'est une mauvaise idée (`managers/campaign.py:203-208`) ; le manager missive
  fait l'inverse.
- `Missive.save()` requête à chaque écriture et jette ses propres défauts : sous
  `update_fields=["status"]` (ce que fait `set_status`), tout ce que calculent
  `_ensure_default_provider`/`_ensure_missive_defaults` est perdu (`models/missive.py:352-356`).
- Les destinataires dupliqués gardent le statut de la tentative précédente (`status`, `sent_at`,
  `delivered_at` non réinitialisés, `models/missive.py:1109-1117`), donc les `pct_recipient_*` de la
  campagne rapportent des états périmés.
- Deux définitions concurrentes de « premier document » : sous-chaîne du nom de fichier
  (`models/attachment.py:229-233`) vs type + priorité 0 (`models/missive.py:902-905`, dont la
  docstring dit « pas par nom de fichier »). Un fichier utilisateur nommé `first-document-x.pdf` est
  silencieusement forcé en priorité 0 et exclu des resends.
- `calculate_priority()` fait `aggregate(Max)` puis écrit, sans contrainte unique sur
  `(missive, priority)` → collisions concurrentes, ordre des pages non déterministe
  (`models/attachment.py:413-429`).
- N+1 sur les FK génériques, recalculé 3× par envoi : `ro.content_object` est une requête par ligne
  (`models/missive.py:829-830`, il manque `prefetch_related("content_object")`), et
  `missive_context()` est reconstruit pour `subject`, `body_rich` *et* `body_text`.
- Les montants font partie de la clé d'upsert de facturation (`billings.py:20-32`) : un montant
  corrigé insère une seconde ligne au lieu de mettre à jour, et `total_billing_amount` somme les deux.
- Supprimer une campagne détruit l'historique des runs (CASCADE) et laisse des brouillons sans contenu
  (`Missive.campaign` en SET_NULL). `can_remove` est purement indicatif, rien ne l'applique
  (`models/scheduler.py:89-95` vs `models/missive.py:102-110`, `models/campaign.py:364-379`).
- Les choices sont construites à l'import depuis les settings et le paquet `pymissive`
  (`models/choices.py:25-26`, `160-172`) : un bump de dépendance génère des `AlterField` sans que
  personne n'édite un modèle. C'est une grande part des 41 `AlterField` de l'historique. Django 5.0+
  accepte un callable pour `choices`, ce qui supprime le couplage.
- `models/missive.py` (1 686 l.) est un véritable objet-dieu : schéma, moteur d'héritage campagne,
  client RPC provider, présentation HTML avec `mark_safe`, construction d'URL, génération PDF,
  pipeline de templates, sérialisation, clonage de 3 modèles liés, machine à états et validation —
  avec une douzaine d'imports locaux pour casser les cycles qui en résultent.
- `can_proofs()` renvoie `self`, donc toujours vrai : les gardes `if not self.can_proofs()` sont mortes
  (`models/missive.py:1512-1530`).
- `print()` de debug en chemin de requête : `models/missive.py:845-847` (offset provider + CSS généré),
  à chaque preview et chaque rendu PDF.

**Surface HTTP / admin**

- `save_proofs` et `download_proof` sont des GET qui appellent le provider et créent des pièces
  jointes : le CSRF ne couvre pas GET (`admin/missive.py:815-839`).
- Les téléchargements de pièces jointes sont anonymes **par design** (un test l'assère,
  `test_attachment_download_view.py:83`) et servent aussi les documents `PROOF` — preuves de
  distribution de LRE, avec données personnelles — en ignorant le flag `linked` (`views/attachment.py:17`).
- Les previews rendent le corps comme un *template Django* contre de vrais objets métier
  (`processors/body/django_template.py:36-41`), avec `|safe`, sur l'origine de l'application : un
  rédacteur de contenu peut exécuter du JS chez les admins et appeler les méthodes sans argument des
  objets liés. Iframe sandboxée ou origine séparée + CSP recommandés.
- `MissiveWebhookAdmin` : `ProviderListFilter.queryset` ignore sa propre valeur (filtre décoratif), et
  la changelist ne marche que grâce à une redirection forcée (`admin/webhook.py:33-35`, `:99-119`).
  `MissiveWebhook.save()`/`delete()` n'appellent jamais `super()`.
- pdf.js chargé depuis `cdnjs.cloudflare.com` sans SRI, puis `fetch` avec `credentials: 'include'`
  (`postal_preview.html:105`, `:124-132`).
- `admin/missive.py` (850 l.) : le triplet `has_X_permission`/`handle_X`/vue de confirmation est
  répété 12 fois à l'identique, dont 3 handlers qui ne sont que des stubs de redirection vers leur
  propre vue de confirmation. À extraire en mixins.
- `views/preview.py:106-164` : ~60 lignes de `try/except (ValueError, TypeError, AttributeError): pass`
  imbriqués pour reconstruire une instance depuis un formulaire invalide ; combiné à
  `build_preview_context` qui avale tout et renvoie `{}`, une preview cassée rend du vide en silence
  au lieu d'échouer bruyamment.

**Outillage**

- `django-pymissive/.github/workflows/ci.yml` est mort **et** faux : GitHub Actions ne lit que le
  `.github/workflows/` racine, et ce fichier lint/teste un paquet `missive` qui n'existe pas
  (`flake8 missive tests`, `pytest --cov=missive`). À supprimer.
- L'extra `pdf` n'est jamais installé en CI : tout le pipeline PDF/watermark (436 l.) est **silencieusement**
  sauté, 20 tests skippés invisibles sans `-rs` (`ci.yml:57`, `conftest.py:54`).
- Les fixtures `tests/fixtures/deposit_proof_*.pdf` ne sont pas commitées (le dossier ne contient qu'un
  `.DS_Store`), d'où 3 tests morts sur la logique réelle d'extraction de numéro de suivi.
- **`python-pymissive` n'a aucun test** : pas de `tests/`, pas de `conftest.py`, pas de config
  pytest. Sa CI se limite à `python -c "import pymissive"`. Les 5 093 lignes du cœur ne sont
  couvertes qu'indirectement, par 12 fichiers de tests de `django-pymissive`, donc seulement sur le
  périmètre qu'utilise l'intégration Django et uniquement avec Django + une base installés.
- Aucune mesure de couverture (`pytest-cov` ni installé ni déclaré).
- Les tests n'isolent pas `MEDIA_ROOT` : `django-pymissive/pymissive/` a atteint 3,8 Mo / 873 fichiers
  de pièces jointes générées. Correctement gitignoré, mais rien ne nettoie.
- **La CI ne peut pas voir une dépendance non déclarée du cœur** : les jobs `django-pymissive` font
  `pip install -e ../python-pymissive` dans un env qui a déjà Django et `requests`, donc l'install
  editable masque complètement les déclarations manquantes. C'est ce qui a laissé passer l'import
  Django dans `maileva.py`, et `discord.py` est encore dans ce cas (`discord.py` non déclaré, mais le
  provider n'est pas implémenté). Un job qui fait `pip install ./python-pymissive` puis importe
  chaque provider fermerait le trou.
- Deps déclarées-non-utilisées côté Django : `babel`, `email-validator` (zéro import dans
  `django-pymissive/src`). L'extra `messaging` pointe sur `python-telegram-bot` alors que Telegram
  n'a aucune implémentation.
- `django_boosted` et `virtualqueryset` sont importés directement (12 fichiers) mais n'arrivent que
  transitivement via `django-providerkit`.
- `providers/` et `providers/todo/` n'ont pas d'`__init__.py` : `find_packages()` ne les découvre pas.
  La wheel les contient aujourd'hui, mais via un comportement setuptools documenté comme déprécié.
- `env.example` publie des slots de credentials pour ~20 providers qu'aucune implémentation ne lit.
- `pymissive>=1.3.13` sans borne haute alors que les deux paquets sont bumpés ensemble à chaque release :
  un `<2` refléterait la réalité.

---

## Ordre de traitement recommandé

1. **Authentifier le webhook** : faire passer les en-têtes de la requête jusqu'à la couche provider
   pour rendre la vérification de signature possible, ajouter un secret par provider dans l'URL
   enregistrée en palliatif, et renvoyer des 4xx/5xx pour que les providers réessaient.
   (P0-1, P1-12)
2. **Scaleway** : supprimer le GET sur `SubscribeURL` ou le restreindre à une allowlist d'hôtes
   Scaleway. Pour `log_sns_credentials`, garder l'affichage mais en faire le défaut, rendre le
   fichier opt-in avec un chemin explicite en `0600`, et réparer l'appel `logger`. (P0-2)
3. **Machine à états** : garde d'état terminal dans `set_status()`, sortir `PROCESSING` du cul-de-sac
   via un timeout/bail, sortir les appels provider des blocs atomiques. (P0-3)
4. **Rendre les annotations du manager missive opt-in**, comme celles du manager campagne — c'est la
   cause racine des compteurs gonflés déjà corrigés, et elle pèse encore sur chaque requête. (P2)
5. **Faire tester la CI sur une install non-editable du cœur**, sinon la prochaine dépendance non
   déclarée passera aussi inaperçue — `discord.py` est déjà dans ce cas. (P2, outillage)
6. Les P1 restants sont chacun des correctifs petits et localisés : `format_html` au lieu de
   `mark_safe`, allowlist sur `download_proof`, `super()` dans `has_change_permission`, décision
   explicite sur `PreviewView`, une migration d'index, `__init__` au lieu de `__init_subclass__`.
7. **Ajouter un test qui instancie chaque provider et appelle ses normalizers.** Les P1-10, le crash
   `get_normalize_event`, le bug d'arg CLI, `get_config_by_support` et les 16 stubs non importables
   auraient tous été attrapés par ce seul test. C'est la condition préalable au reste.
