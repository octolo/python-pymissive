"""Shared helpers for admin actions that mutate or spend."""

from urllib.parse import unquote

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse


class ActionRightsMixin(admin.ModelAdmin):
    """Make ``django_boosted`` actions respect the Django change permission.

    A boost view left on the default ``view`` permission also demands
    ``has_change_permission`` on POST. That hook stays False for an immutable
    event, a locked missive and a virtual webhook, so those views declare the
    Django permission codename instead. Their body still calls
    :meth:`require_action_rights`.

    Submit actions (``@admin_boost_action``) are dispatched only for actions
    listed by ``get_submit_actions``.
    """

    def has_action_rights(self, request, obj=None) -> bool:
        # ModelAdmin directly: AdminBoostModel would answer True, and this
        # admin's own override refuses any POST on a locked missive, which
        # would wrongly disable cancel/delete/retrieve — they need a sent one.
        return admin.ModelAdmin.has_change_permission(self, request, obj)

    def require_action_rights(self, request, obj=None) -> None:
        if not self.has_action_rights(request, obj):
            raise PermissionDenied

    def get_action_object(self, request, object_id):
        return self.get_object(request, unquote(str(object_id)))

    def redirect_to_change(self, obj):
        opts = obj._meta
        return redirect(reverse(f"admin:{opts.app_label}_{opts.model_name}_change", args=[obj.pk]))

    def redirect_to_boost_view(self, request, object_id, view_name):
        """The three send/resend/delete handlers are only this redirect."""
        obj = self.get_action_object(request, object_id)
        opts = self.model._meta
        return redirect(
            reverse(
                f"admin:{opts.app_label}_{opts.model_name}_{view_name}",
                args=[obj.pk],
            )
        )

    def call_object_method(self, request, object_id, method_name, success_message):
        obj = self.get_action_object(request, object_id)
        getattr(obj, method_name)()
        messages.success(request, success_message)
        return obj

    def confirm_action(self, request, obj, confirmed, message):
        """Gate a boost confirm view. Returns the confirm payload, or None."""
        self.require_action_rights(request, obj)
        if not confirmed:
            return {"confirm": message}
        return None
