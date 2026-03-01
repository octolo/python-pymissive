from django_providerkit.models.service import ProviderServiceModelBase
from django.utils.translation import gettext_lazy as _
from django_providerkit.managers.service import ProviderServiceManager
from django.db import models

class MissiveServiceModel(ProviderServiceModelBase):
    """Virtual model for missive services."""

    objects = ProviderServiceManager(package_name='pymissive')

    class Meta:
        managed = False
        verbose_name = _('Provider Service')
        verbose_name_plural = _('Provider Services')