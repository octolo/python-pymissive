# Proposition : rendu Discord / Slack / Teams

## Constat

- Discord et Slack ne rendent pas le HTML : les balises s'affichent telles quelles. Teams accepte quelques balises dans une `MessageCard`, mais pas de façon fiable.
- Les trois providers envoient `body_text or body_rich` tel quel. Si seul `body_rich` est rempli, le HTML brut part dans le message.
- Aucun des trois providers n'envoie de fichiers : les pièces jointes sont ignorées sans message.
- `add_attachments_linked` ne fonctionne que pour l'email.
- La preview n'a pas de template `branded` : elle retombe sur `base_preview.html`.

## 1. Langage source : un sous-ensemble de markdown standard

On écrit le message une seule fois, dans `body_text`, en markdown standard limité à ce que les trois applications savent afficher. La conversion vers chaque application se fait à l'envoi.

| Syntaxe | Discord | Teams | Slack (après conversion) |
|---|---|---|---|
| `**gras**` | natif | natif | `*gras*` |
| `*italique*` | natif | natif | `_italique_` |
| `~~barré~~` | natif | natif | `~barré~` |
| `[texte](url)` | natif | natif | `<url\|texte>` |
| `- liste` | natif | natif | `• liste` |
| `> citation`, `` `code` `` | natif | natif | natif |

On évite ce qui ne passe pas partout : titres `#`, tableaux, images, souligné, HTML et mentions (chaque application a sa propre syntaxe).

Ce choix a plusieurs avantages :
- Discord et Teams lisent ce markdown sans conversion.
- Pour Slack, la conversion se limite à quelques remplacements.
- Le texte reste lisible tel quel, même si une conversion manque.
- WhatsApp pourra s'ajouter plus tard avec le même principe.

Si `body_text` est vide, on convertit `body_rich` (HTML) vers ce même markdown. C'est un filet de sécurité, pas le chemin recommandé.

## 2. Adapter le message à la brand

Il y a un seul processor, `adapt_for_brand` (`processors/body/branded.py`). Il lit la brand sur le provider du missive (`provider._provider.name`, pas le champ `brand_name`, qui désigne la marque de l'expéditeur) et applique dans l'ordre :

1. `body_rich` HTML vers markdown si besoin (`html.parser` de la stdlib, sans dépendance ajoutée) ;
2. ajout des pièces jointes en liens `[nom](url)` à la fin du message ;
3. conversion vers le dialecte de la brand (Slack seulement pour l'instant) ;
4. troncature à la limite de l'application (Discord : 2000 caractères ; Slack : ~4000 conseillés).

Pour l'activer, on ajoute une chaîne par défaut propre au type `branded` dans `Missive.get_default_body_processors()` :

```python
DEFAULT_BODY_PROCESSORS_BY_TYPE = {
    "branded": [TEMPLATE, "django_pymissive.processors.body.branded.adapt_for_brand"],
}
```

Comme le processor détecte lui-même la brand, il n'y a pas de réglage à faire par provider. L'envoi et la preview passent par la même chaîne, donc la preview montre exactement ce qui part. L'ordre de priorité reste : missive > campagne > type > global.

Le signal `missive_pre_send` existe déjà et reste disponible pour les cas propres à un projet. Il ne suffit pas à lui seul, car la preview ne passe pas par `send_missive`.

## 3. Pièces jointes en lien

On ajoute un attribut de classe sur `DiscordProvider`, `SlackProvider` et `TeamsProvider` dans `pymissive` :

```python
attachments_as_links = True
```

Quand cet attribut est présent, `Missive.get_serialized_attachments` ignore le filtre `linked` (comme pour le postal) et renvoie toutes les pièces jointes sous forme d'URL. Aucune n'est perdue. Les providers prennent alors `body_text` compilé en priorité.

## 4. Templates de preview par brand

`template_for_missive` renvoie une liste. Django prend le premier template qui existe :

```python
if mt == "branded":
    return [
        f"django_pymissive/branded/{brand}_preview.html",
        "django_pymissive/branded_preview.html",
    ]
```

Les deux vues de preview utilisent déjà cette fonction. Un projet peut surcharger `branded/slack_preview.html` dans ses propres templates sans toucher à la lib.

| Template | Rendu |
|---|---|
| `branded_preview.html` | Générique : bulle de chat neutre, texte en `pre-wrap`, liens via `urlize` |
| `branded/discord_preview.html` | `@skyra/discord-components` (web components, fichier statique) : thème sombre, badge bot |
| `branded/slack_preview.html` | `slack-to-html` (navigateur, sans dépendance) pour le mrkdwn + CSS maison : fond blanc, avatar carré |
| `branded/teams_preview.html` | CSS maison : carte avec barre `#0078D4`, titre (`subject`) et texte |

Tous les templates héritent de `base_preview.html` et affichent `body_text_compiled`, c'est-à-dire le texte déjà adapté.

On peut commencer avec du CSS maison partout, puis brancher les deux bibliothèques JavaScript. Elles ne demandent pas de build et pas de dépendance Python.

Pour la preview de campagne, il faut ajouter `?type=branded&brand=slack` : `brand` fixe le provider du missive de preview. Sans `brand`, on prend le provider par défaut de `MissiveConfig`.

## Découpage proposé

1. Côté `pymissive` : `attachments_as_links` et priorité à `body_text` dans les trois providers.
2. Le processor `adapt_for_brand` et ses tests (conversion HTML, dialecte Slack, troncature).
3. La chaîne par défaut par type dans `get_default_body_processors()`.
4. `template_for_missive` avec repli, `?brand=` pour la preview de campagne, puis les templates.

Aucun changement de schéma, donc pas de migration.

## Questions ouvertes

- Une campagne multicanal qui a ses propres `body_processors` (pensés pour l'email) passe devant la chaîne `branded`. Faut-il, pour ce type, ajouter `adapt_for_brand` systématiquement à la fin ?
- Faut-il un champ dédié au texte branded sur la campagne, ou réutiliser `body_text` (partagé avec le SMS) ?
- WhatsApp : formatage proche de Slack, mais sans syntaxe de lien. Il faudrait un dialecte qui écrit l'URL en clair.
