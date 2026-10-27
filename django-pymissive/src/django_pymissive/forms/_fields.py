"""Helpers for dynamically declared form fields."""

from typing import Any

from django import forms
from django.db import models


def model_formfield(
    model: type[models.Model],
    field_name: str,
    **kwargs: Any,
) -> forms.Field:
    """Build a form field from a concrete model field."""
    model_field = model._meta.get_field(field_name)
    if not isinstance(model_field, models.Field):
        raise TypeError(f"{model.__name__}.{field_name} is not a concrete model field")

    form_field = model_field.formfield(**kwargs)
    if form_field is None:
        raise TypeError(f"{model.__name__}.{field_name} does not define a form field")
    return form_field
