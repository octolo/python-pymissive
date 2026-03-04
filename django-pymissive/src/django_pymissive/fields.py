from django.db import models


class RichTextField(models.TextField):

    def formfield(self, **kwargs):
        from django.conf import settings
        from django.utils.module_loading import import_string

        widget_path = getattr(
            settings,
            "PYMISSIVE_RICHTEXT_WIDGET",
            "django.forms.Textarea"
        )
        widget_class = import_string(widget_path)

        kwargs["widget"] = widget_class
        return super().formfield(**kwargs)