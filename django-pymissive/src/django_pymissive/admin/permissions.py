"""Shared helpers for admin actions that mutate or spend."""

from urllib.parse import unquote

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse


class ActionRightsMixin:
    """Make ``django_boosted`` actions respect the Django change permission.

    The library grants change permission to any admin declaring changeform
    actions, enforces only ``has_view_permission`` on its boost views, and
    derives button availability from the ``has_<action>_permission`` hooks —
    which describe object state, not user rights. Without this, a staff account
    holding nothing but view permission can trigger a send.

    Submit actions (``@admin_boost_action``) are genuinely enforced: a POST is
    dispatched only for actions listed by ``get_submit_actions``. Boost views
    (``@admin_boost_view``) are not, so the mutating ones must call
    :meth:`require_action_rights` in their own body.
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
        return redirect(
            reverse(f"admin:{opts.app_label}_{opts.model_name}_change", args=[obj.pk])
        )

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
