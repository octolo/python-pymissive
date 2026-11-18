"""Change link on every inline, including proxy models.

Django shows the link only when the inline model itself is registered. Channel
steps, recipients and attachments are proxies of a registered model, so the
link opens that admin. The row's primary key is the same.
"""

from django.contrib import admin
from django.contrib.admin.options import InlineModelAdmin


class ShowChangeLinkMixin(InlineModelAdmin):
    show_change_link = True
    change_link_url_name = ""

    def __init__(self, parent_model, admin_site):
        super().__init__(parent_model, admin_site)
        target = _change_target(admin_site, self.model)
        if target is None:
            return
        opts = target._meta
        self.change_link_url_name = f"admin:{opts.app_label}_{opts.model_name}_change"
        if isinstance(self, admin.StackedInline):
            self.template = "django_pymissive/admin/edit_inline/stacked.html"
        else:
            self.template = "django_pymissive/admin/edit_inline/tabular.html"


def _change_target(admin_site, model):
    if admin_site.is_registered(model):
        return model
    concrete = model._meta.concrete_model
    if concrete is not model and admin_site.is_registered(concrete):
        return concrete
    return None
