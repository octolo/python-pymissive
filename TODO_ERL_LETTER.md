# TODO — `lre` → `erl`, et introduction du type « regular letter »

## Besoin

1. **On code en anglais.** `lre` est l'acronyme français (*lettre recommandée
   électronique*). La clé doit devenir `erl` (*electronic registered letter*).
   Le libellé, lui, est déjà anglais : `"lre": "Electronic registered letter (LRE)"`
   — seules la clé et l'acronyme entre parenthèses sont à reprendre.
2. **Prévoir la lettre simple comme type de plein droit.** Aujourd'hui le
   courrier simple est un `lre` sans `acknowledgement_of_receipt`, et
   `MailevaProvider.get_lre_mode()` en déduit `mail` vs `registered_mail`. On veut
   la même lisibilité que côté e-mail, où `email` et `ere` sont deux types
   distincts :

   | Support | Simple | Recommandé |
   | --- | --- | --- |
   | `email` | `email` | `ere` |
   | `address` | **`letter`** (à créer) | **`erl`** (ex-`lre`) |

   À noter : `ere` respecte déjà la convention anglaise. C'est exactement
   l'incohérence que ce chantier supprime.

Cible :

```python
GENERIC_SUPPORT = {
    "address": ["letter", "erl", "hand_delivery"],
    ...
}
```

## Décisions à trancher avant de coder

- [ ] **Nom du type simple.** `letter` (symétrique de `email`) ou
      `regular_letter` (explicite) ? `letter` entre en résonance avec le layout
      A4 existant (`letter_page.css`, `is_letter_layout`, `LETTER_LAYOUT_TYPES`),
      qui désigne la mise en page et non le type — risque de confusion à la
      lecture.
- [ ] **Compatibilité des données.** `missive_type='lre'` existe en base chez les
      intégrations. Data migration `lre → erl` fournie par la lib, ou résolution
      par alias en lecture ? Un alias seul ne suffit pas : le type sert à
      construire les noms de services provider (`f"send_{missive_type}"`), donc
      toute ligne restée en `lre` chercherait `send_lre`. Piste recommandée :
      data migration côté intégration + alias accepté uniquement en entrée
      (API, CLI, query strings).
- [ ] **Méthodes provider.** `MailevaProvider` porte 20 méthodes suffixées
      `_lre` (`send_lre`, `create_lre`, `retrieve_lre`, `get_billings_lre`,
      `tracking_number_lre`, `create_webhook_lre`, `address_offset_lre`, …),
      résolues par interpolation de chaîne. Renommer en `_erl` avec des alias
      `send_lre = send_erl` le temps d'un cycle de version, ou introduire une
      indirection type → suffixe de service ?
- [ ] **Colonnes `*_lre` de `MissiveCampaign`** : `acknowledgement_lre`,
      `delivery_mode_lre`, `priority_lre` (mappées dans `models/missive.py`
      ~371-373). Les renommer touche le schéma. Dans le périmètre « acronyme »
      ou hors périmètre ? Si on renomme : `_erl`, ou suffixe supprimé puisque ces
      réglages valent pour tout le support `address` ?
- [ ] **`count_error` vs `count_missive_error`** (reporté depuis
      `ANNOTATIONS_REVIEW.md`, à traiter ici puisque ce chantier renomme déjà des
      annotations). `count_error` couvre les trois `ERROR_STATUSES`,
      `count_missive_error` le seul statut `error` — et sur un run les deux
      diffèrent en plus par le périmètre de thread (`MISSIVE` pour le premier,
      tentatives archivées incluses pour le second). Options : ne rien changer et
      documenter ; `count_missive_<statut>` → `count_status_<statut>` ;
      `count_error` → `count_errors`. Même angle mort que `count_type_lre`
      ci-dessous : un consommateur qui lit l'annotation par son nom casse
      silencieusement.
- [ ] **Le type simple partage-t-il l'implémentation Maileva ?** L'API est la
      même, seul le mode change (`mail` / `registered_mail`). Le mode devrait
      alors se déduire **du type** et non plus seulement de
      `acknowledgement_of_receipt`, ce qui rend les deux sources de vérité
      cohérentes.

## Périmètre — inventaire

~250 occurrences de `lre` / `LRE` :

| Zone | Occurrences | Notes |
| --- | --- | --- |
| `python-pymissive/src` | ~41 | dont 20 dans `providers/maileva.py`, 11 dans les `commands/`, 6 dans `config/` |
| `django-pymissive/src` | ~25 | `models/missive.py`, `models/campaign.py`, `shortcuts.py`, `pdf.py`, `views/preview.py`, `utils.py`, `events.py`, `managers/related_object.py` |
| Traductions | 7 | `translation_catalog.py`, `locale/fr/LC_MESSAGES/django.po` |
| Tests | ~67 sur 17 fichiers | surtout `test_export_billings_csv`, `test_retrieve_billings`, `test_support_annotations`, `test_retrieve_from_provider` |
| Docs / README / `env.example` | ~45 | `docs/commands/*.md`, `commands/_docs/*.md`, les deux README |
| Migrations existantes | 19 sur 6 fichiers | **à ne pas retoucher** : elles décrivent un état passé |

## Étapes

1. [ ] `pymissive.config` : renommer la clé dans `address.TYPES`, ajouter le type
       simple, mettre à jour `GENERIC_SUPPORT["address"]`.
2. [ ] Alias d'entrée : `lre → erl` (et `postal → letter` au niveau **type**).
       Attention à ne pas casser `normalize_support("postal") == "address"`, qui
       opère au niveau **support** — les deux tables sont distinctes.
3. [ ] `MailevaProvider` : renommer les méthodes `*_lre`, brancher le type simple,
       dériver le mode du type. Idem pour les squelettes
       `providers/todo/{ar24,certeurope}.py`.
4. [ ] CLI (`commands/missive.py`, `billing.py`, `attachment.py`) : le défaut
       codé en dur `missive_type = "lre"` (`commands/missive.py` ~199) et les
       exemples de `_docs/`.
5. [ ] django-pymissive : `shortcuts.send_lre` → `send_erl` (+ `send_letter`
       généré automatiquement), `LETTER_LAYOUT_TYPES` dans `pdf.py`, la table de
       templates de `views/preview.py`, `check_lre`,
       `get_provider_address_css_lre`.
6. [ ] Traductions : garder l'affichage FR (« LRE », « Lettre recommandée
       électronique ») — seule la clé change. Ajouter le libellé du type simple,
       régénérer le `.po`.
7. [ ] Tests : renommer, et **ajouter** un test qui distingue `letter` de `erl`
       de bout en bout (choix du mode provider, layout A4, compteurs par support).
8. [ ] Docs, README, `env.example`, commentaire de `pyproject.toml`.
9. [ ] Migration Django (choices sur `missive_type`) : à générer manuellement.

## Points de vigilance

- **Annotations nommées.** `count_type_lre` devient `count_type_erl` : tout
  consommateur qui lit l'annotation par son nom casse silencieusement (il lira
  un attribut absent). `count_support_address` couvre les trois types tout seul
  et ne bouge pas — c'est le remplacement à conseiller.
- **`lre_qualified`** traîne dans `pdf.py` et `views/preview.py` alors qu'il
  n'existe dans aucun `MISSIVE_TYPES` : à supprimer ou documenter au passage.
- **`hand_delivery`** reste un type à part : il ne devient ni `letter` ni `erl`.
- Ne pas toucher aux migrations déjà livrées ; l'état migré porte les anciens
  `choices`, c'est normal.

## Vérification

```bash
cd django-pymissive && python -m pytest -q     # 3 échecs pré-existants (fixtures PDF Maileva)
rg -n '\blre\b|\bLRE\b' --glob '!**/migrations/**' --glob '!**/*.po'   # doit ne plus rien rendre hors libellés FR
python manage.py makemigrations django_pymissive --check --dry-run
```
