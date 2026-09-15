# Découper `Missive` — objet-dieu

Périmètre : `django-pymissive/src/django_pymissive/models/missive.py` (~1 760 l.).
Ce n’est **pas un bug**. Rien ici n’envoie deux fois, n’ouvre le webhook, ni ne
bloque un déploiement. C’est de la dette d’architecture : le fichier fait trop
de métiers, donc chaque vrai correctif est plus lent et plus risqué.

`REVIEW.md` ne reprend plus ce point. Ce document est le plan.

---

## Le problème

`Missive` devrait surtout être **la ligne en base** : type, statut, `external_id`,
liens campagne / destinataires / pièces.

Aujourd’hui le même fichier est aussi :

| Rôle | Exemples |
| --- | --- |
| Schéma Django | champs, `save`, défauts, managers |
| Héritage campagne | `get_locally_or_campaign_value`, `apply_campaign_config`, `set_locally_ifnull` |
| Client provider | `call_provider_service`, send / retrieve / cancel / delete |
| Machine à états | `set_status`, `reclaim_stale_processing`, transitions d’envoi |
| Pipeline templates | `*_compiled`, `apply_body_processors` |
| Génération PDF | `body_to_pdf`, `generate_first_document`, `ensure_first_document` |
| Présentation admin | `mark_safe`, `show_attachments_linked`, `show_preview_browser` |
| URLs / tokens | `get_browser_preview_path`, `token_missive`, `get_webhook_url` |
| Sérialisation | `get_serialized_data`, `get_serialized_attachments` |
| Clonage | `duplicate_missive` + destinataires / pièces / related objects |
| Validation | `can_send`, `check_email`, `check_lre`, … |

Les imports locaux (`from ..views.preview`, `from ..events`, `from ..billings`,
…) existent pour casser des cycles : tout le monde importe `Missive`, donc
charger le modèle tire les vues, qui rechargent le modèle.

Un fix statut peut casser le PDF, et l’inverse. Ce n’est pas un défaut de
comportement, c’est un coût de maintenance.

---

## Ce qu’on laisse sur le modèle

Ça, c’est le métier de la **ligne** :

- champs et `save` (défauts uniquement sur un write complet, pas sur
  `update_fields`)
- héritage campagne
- `set_status` et les gardes (`CANCELLED` terminal, pas de retour à `DRAFT`)
- validations `can_send` / `check_*`
- propriétés de données (`sender`, `recipients`, `is_postal_like` une fois
  extraite de `views.preview`)

---

## Ce qu’on sort — ordre

Pas de big-bang. Un paquet = un PR, les tests existants doivent passer. Les
méthodes actuelles peuvent rester un temps comme **façades d’une ligne** qui
délèguent, pour ne pas casser l’admin ni les appels `missive.send_missive()`.

### 1. Présentation (le plus simple, zéro risque métier)

`show_attachments_linked`, `show_attachments_linked_text`,
`show_preview_browser`, `show_preview_browser_text`, templates `mark_safe`.

Ça n’appartient pas à la ligne SQL. Destination : l’admin, ou
`django_pymissive/presenters/missive.py`. Le modèle garde des données et des
URLs, pas du HTML.

### 2. Casser les imports circulaires

Aujourd’hui `missive.py` importe `views.preview` en local
(`POSTAL_PREVIEW_MISSIVE_TYPES`, `build_preview_context`).

Extraire le postal / preview context dans un module neutre
(`postal.py` ou `preview_context.py`) qui n’importe ni les vues ni le modèle
comme point d’entrée. `is_postal_like` et le contexte lettre n’ont plus besoin
des vues.

### 3. Envoi / retrieve / cancel

`send_missive`, `resend_missive`, `retrieve_missive`, `call_provider_service`
→ un service (`missive_send.py` ou équivalent) qui **reçoit** une `Missive`.

Le modèle garde `can_send`, le statut, `external_id`. C’est là que vivent les
vrais bugs (transaction autour du provider, `REQUEST` sans destinataire,
etc.) : un fichier plus mince aide à les voir.

### 4. PDF + templates

`body_to_pdf`, `generate_first_document`, `*_compiled` s’appuient déjà sur
`processors/`. Les laisser comme façades d’une ligne, ou les pousser
entièrement dans ce paquet.

### 5. Clonage

`duplicate_missive` / `duplicate_attachments` / `duplicate_recipients` /
`duplicate_related_objects` peuvent suivre le send, plus tard. Pas urgent.

---

## Quand ne pas le lancer

Ce découpage n’est pas prioritaire tant que les P2 Django de `REVIEW.md`
(annotations du manager missive, N+1, preview) restent ouverts. Il n’améliore
pas la sécurité ni la délivrabilité.

---

## Critère de fin

- `models/missive.py` n’importe plus `views`, `processors`, ni ne contient de
  `mark_safe`
- send / retrieve / cancel n’ont plus de logique provider dans le modèle
  (façade OK)
- aucun changement de comportement : la suite Django existante suffit, pas
  besoin d’une nouvelle batterie de tests « de découpage »
