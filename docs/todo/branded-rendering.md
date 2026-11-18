# Branded message rendering

Discord, Slack, and Teams still receive the message body as stored. Preview
templates exist, but they do not adapt that body to each application.

No schema change is required.

## Current behaviour

- Discord, Slack, and Teams send `body_text`, then `body_rich`, then
  `subject`. HTML in `body_rich` is sent unchanged.
- None of the three providers uploads files. Attachments are dropped.
- `add_attachments_linked` only appends links to email bodies.
- Preview selects `branded/{brand}_preview.html`, then
  `branded_preview.html`. The brand comes from the provider's
  `preview_brand`, not from the sender's `brand_name`.
- Discord, Slack, Teams, and the generic fallback are custom CSS templates.
  They show escaped `body_text_compiled`, or `body_rich_compiled` with its
  tags removed.
- A campaign preview accepts `?type=branded&brand=slack&step=<id>`. Without
  a valid `brand`, it uses the generic template.
- Processor resolution is missive, then its campaign step, then the
  campaign, then the global default. There is no chain selected by missive
  type.

## Source language

Write the message once in `body_text`, using the markdown subset all three
applications can represent. Convert it for the destination at send time.

| Syntax | Discord | Teams | Slack, after conversion |
| --- | --- | --- | --- |
| `**bold**` | native | native | `*bold*` |
| `*italic*` | native | native | `_italic_` |
| `~~strike~~` | native | native | `~strike~` |
| `[text](url)` | native | native | `<url\|text>` |
| `- list` | native | native | `• list` |
| `> quote`, `` `code` `` | native | native | native |

Avoid headings, tables, images, underline, HTML, and mentions. Each
application has its own mention syntax.

Discord and Teams can keep this markdown. Slack needs only a small set of
replacements. The source stays readable when conversion is missing. WhatsApp
can follow the same path later.

When `body_text` is empty, convert `body_rich` from HTML to this markdown.
That is a fallback, not the recommended authoring path.

Each campaign step already has its own `body_text`, so a branded step does
not share its text with an SMS step.

## `adapt_for_brand`

Add one processor, `django_pymissive.processors.body.branded.adapt_for_brand`.
It reads `preview_brand` from the missive provider and applies, in order:

1. HTML in `body_rich` to the shared markdown, using the standard-library
   `html.parser`, when `body_text` is empty;
2. campaign and missive attachments as `[name](url)` links at the end;
3. the Slack dialect, when the brand is Slack;
4. truncation to the application limit: 2,000 characters for Discord and
   about 4,000 for Slack.

The processor belongs to the branded default body chain, after the template
processor:

```python
DEFAULT_BODY_PROCESSORS_BY_TYPE = {
    "branded": [
        TEMPLATE,
        "django_pymissive.processors.body.branded.adapt_for_brand",
    ],
}
```

Send and preview must use that same chain, so the preview shows the text
that will be sent. `missive_pre_send` remains available for project-specific
work, but preview does not call `send_missive`.

The providers already prefer `body_text`. They do not need a separate
attachment mode: they ignore the attachment payload, so the links have to be
part of the compiled text.

## Preview

The template fallback and `?brand=` parameter are already in place. Keep the
current CSS templates. JavaScript renderers such as Discord web components
or a Slack markdown renderer can replace the CSS later; they are not part
of this change.

Once `adapt_for_brand` runs in the body pipeline, these templates display
the adapted `body_text_compiled` without further template changes.

## Remaining work

1. Add `adapt_for_brand`, with tests for the HTML fallback, Slack dialect,
   attachment links, and truncation.
2. Select the branded default chain by missive type inside
   `get_default_body_processors()`.
3. Cover a branded step whose own chain is empty and whose campaign chain
   is also empty.

## Open questions

- A campaign or step chain written for email replaces the branded default.
  Should `adapt_for_brand` always run at the end for a branded missive?
- WhatsApp formatting is close to Slack, but it has no link syntax. Its
  dialect needs to print the URL as plain text.
