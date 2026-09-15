from django import template

from ..preview_sandbox import sandboxed_preview_srcdoc

register = template.Library()


@register.inclusion_tag("django_pymissive/includes/sandboxed_html.html")
def sandboxed_html(html, title=""):
    """Render ``html`` in a fully sandboxed iframe, or nothing when empty."""
    if not html:
        return {"srcdoc": "", "title": title}
    return {"srcdoc": sandboxed_preview_srcdoc(str(html)), "title": title}
