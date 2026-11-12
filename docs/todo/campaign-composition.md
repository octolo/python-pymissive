# Composer les campagnes par étapes

## Objectif

Remplacer progressivement la configuration monolithique de
`MissiveCampaign` par une composition d'étapes typées, ordonnées et propres à
chaque campagne.

Une campagne pourra notamment contenir :

- un email ;
- un courrier ;
- un deuxième email avec un contenu et des fichiers différents ;
- une étape branded pour Discord, Slack, WhatsApp ou un autre canal ;
- plusieurs étapes du même type.

La présence d'une étape l'active. Il n'est donc pas nécessaire d'ajouter un
booléen d'activation.

## Sémantique retenue

- Les étapes appartiennent à une seule campagne et ne sont pas réutilisables
  entre campagnes.
- Elles sont lancées dans l'ordre de leur position.
- Cet ordre ne constitue pas un workflow : il n'y a ni délai, ni condition, ni
  dépendance au succès de l'étape précédente.
- L'échec d'une étape ne bloque pas les suivantes.

## Architecture cible

### `MissiveCampaign`

`MissiveCampaign` reste l'agrégat principal et conserve :

- son identité et son libellé ;
- sa description ;
- son contexte et sa configuration globale ;
- ses relations vers les cibles, exécutions et missives ;
- le lancement et la progression globale de la campagne.

Le champ `subject` actuel devient le libellé de la campagne. Les sujets propres
aux emails sont portés par leurs étapes.

### `CampaignStep`

Ajouter un modèle central avec au minimum :

- `campaign` ;
- `position` ;
- `label` ;
- `missive_type`.

Une contrainte unique sur `(campaign, position)` garantit l'ordre. Plusieurs
étapes d'une campagne peuvent avoir le même `missive_type`.

Ce modèle central permet à `Missive`, `CampaignTarget`, aux fichiers et au
scheduler de référencer une étape sans relation générique.

### Configuration des étapes

`CampaignStep` porte directement l'ensemble des champs disponibles. Des
modèles proxy email, téléphone, courrier et application/branded exposent
uniquement les champs utiles à leur famille dans l'administration :

- expéditeur et reply-to ;
- sujet et contenu ;
- accusé de réception ;
- options d'impression ou de livraison ;
- `brand_name` pour les applications branded ;
- contexte, configuration et processeurs propres à l'étape.

La configuration application/branded ne réutilise plus implicitement les
champs `phone_*`.

Le courrier utilise les champs communs `body_rich` et
`body_rich_snapshot_html`. Le proxy postal expose également les propriétés
`first_document` et `first_document_snapshot_html` comme alias Python. Comme
un proxy Django ne peut pas ajouter de champ de base de données, son formulaire
admin affiche les champs communs avec des libellés postaux.

## Fichiers de campagne par étape

Les fichiers restent possédés par la campagne via
`MissiveBaseAttachment.campaign`. Le champ M2M
`MissiveBaseAttachment.campaign_step` choisit précisément les étapes qui
utilisent chaque fichier. Il est affiché uniquement pour les pièces jointes
de campagne.

L'ordre reste celui du champ `priority` de la pièce jointe de campagne. Il
n'existe ni second point de gestion depuis `CampaignStep`, ni ordre distinct
par étape.

Cette structure permet :

- d'ajouter un fichier à un email sans l'ajouter aux courriers ;
- de partager le même fichier entre plusieurs emails ;
- de connaître les étapes utilisant un fichier sans dupliquer le fichier
  stocké.

Le premier document généré pour un courrier reste propre à sa configuration
postale. Il ne doit pas être confondu avec les pièces jointes M2M.

Pendant la transition, un ancien fichier de campagne sans association à une
étape conserve le comportement global actuel. Les nouveaux fichiers doivent
avoir des étapes explicitement sélectionnées.

## Résolution de la configuration

Ajouter une FK `campaign_step` à `Missive`.

La FK concrète `Missive.campaign` est supprimée. Une missive de campagne
référence uniquement son étape ; `campaign` et `campaign_id` restent
disponibles comme propriétés Python en lecture seule, dérivées de
`campaign_step.campaign`. Une missive autonome conserve un `campaign_step`
vide.

La résolution des valeurs doit ensuite suivre :

1. la valeur locale de la missive ;
2. les champs de son étape ;
3. les valeurs globales ou settings existants.

Lors de la matérialisation d'une missive, seules les pièces jointes associées à
son étape sont copiées. Les anciens fichiers globaux restent inclus pendant la
période de compatibilité.

## Ciblage

Relier `CampaignTarget` à `CampaignStep`.

La contrainte d'unicité actuelle fondée sur `missive_type` doit devenir une
unicité par étape. Un même destinataire pourra alors recevoir deux emails ou
deux courriers distincts dans la même campagne.

Le type de missive de la cible doit correspondre à celui de l'étape.

## Exécution ordonnée

Adapter la matérialisation et le scheduler pour :

1. charger les étapes par `position` ;
2. matérialiser les cibles de l'étape courante ;
3. envoyer les missives de cette étape ;
4. continuer avec l'étape suivante, même si certaines missives ont échoué.

La reprise et le retry doivent s'appuyer sur la FK `campaign_step`. L'ordre
doit rester déterministe après une interruption.

La progression doit être disponible par étape tout en conservant les totaux
actuels par `missive_type`.

## Snapshots

Versionner `campaign_snapshot` et y stocker :

- la version du format ;
- la campagne ;
- la liste ordonnée des étapes ;
- la configuration de chaque étape ;
- les identifiants et l'ordre des fichiers associés.

Les anciens snapshots plats doivent rester lisibles.

## Administration et previews

Remplacer les fieldsets email, téléphone et courrier de la campagne par :

- une liste ordonnée des étapes ;
- un écran de configuration adapté au type de l'étape ;
- une sélection multiple des fichiers de la campagne ;
- une preview identifiée par l'étape, et non uniquement par le type.

L'administration d'un fichier doit également afficher les étapes qui
l'utilisent.

## Transition

Les champs propres aux canaux sont supprimés de `MissiveCampaign`. La reprise
des campagnes existantes vers leurs étapes doit donc être réalisée avant
d'appliquer la suppression des colonnes.

Les migrations sont séparées afin que la reprise lise encore les anciennes
colonnes avant leur suppression.

## Fichiers principaux concernés

- `django-pymissive/src/django_pymissive/models/campaign.py`
- `django-pymissive/src/django_pymissive/models/campaign_target.py`
- `django-pymissive/src/django_pymissive/models/missive.py`
- `django-pymissive/src/django_pymissive/models/attachment.py`
- `django-pymissive/src/django_pymissive/models/scheduler.py`
- `django-pymissive/src/django_pymissive/services/send.py`
- `django-pymissive/src/django_pymissive/admin/campaign.py`
- `django-pymissive/src/django_pymissive/views/preview.py`

## Vérification

Ajouter au minimum les scénarios suivants :

- deux étapes email avec des contenus différents ;
- deux étapes courrier avec des options différentes ;
- un destinataire ciblé par deux étapes du même type ;
- ordre de lancement déterministe ;
- poursuite après l'échec d'une étape ;
- retry après interruption ;
- fichier utilisé par un email mais pas par un courrier ;
- fichier partagé par deux emails ;
- branded distinct de phone ;
- snapshot versionné ;
- preview par étape ;
- lecture d'une campagne et d'un snapshot historiques.

## Migrations

1. `0037_campaignstep_and_more` crée `CampaignStep`, les proxies et les
   nouvelles relations sans supprimer l'ancien schéma ;
2. `0038_migrate_campaign_steps` crée une étape par type utilisé, copie les
   contenus et options de canal, puis relie les missives et les cibles ;
3. `0039_remove_legacy_campaign_fields` supprime `Missive.campaign` et les
   anciennes colonnes email, téléphone et courrier de `MissiveCampaign`.

Un fichier sans étape sélectionnée reste joint à toutes les étapes de sa
campagne.
