"""HTTP adapters for the shared missive-based preview service."""

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.forms import modelform_factory
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.decorators import method_decorator
from django.views.generic import DetailView, View

from ..models.campaign import MissiveCampaign
from ..models.campaign_step import CampaignStep
from ..models.campaign_target import CampaignTarget
from ..models.choices import MissiveRecipientType
from ..models.missive import Missive
from ..models.recipient import MissiveRecipient
from ..services import preview as preview_service

DEFAULT_TEMPLATE = preview_service.DEFAULT_TEMPLATE
POSTAL_PREVIEW_MISSIVE_TYPES = preview_service.POSTAL_PREVIEW_MISSIVE_TYPES
build_preview_context = preview_service.build_preview_context
campaign_preview_query = preview_service.campaign_preview_query
_missive_brand = preview_service.missive_brand
missive_for_campaign_preview = preview_service.missive_for_campaign_preview
missive_for_target_preview = preview_service.missive_for_target_preview
preview_kind_for_missive_type = preview_service.preview_kind_for_missive_type
template_for_missive = preview_service.template_for_missive


_PREVIEW_MODEL = {
    "missive": Missive,
    "campaign": MissiveCampaign,
    "campaign_step": CampaignStep,
    "target": CampaignTarget,
}


def _brand_from_request(request, post_data=None) -> str:
    raw = request.GET.get("brand")
    if not raw and post_data is not None:
        raw = post_data.get("_preview_brand")
    return preview_service.normalize_brand(raw)


def campaign_step_from_request(request, campaign):
    """Step selected by ``?step=``, when it belongs to *campaign*."""
    raw = str(request.GET.get("step") or "").strip()
    if not raw or campaign is None or not getattr(campaign, "pk", None):
        return None
    from ..models.campaign_step import CampaignStep

    step = CampaignStep.objects.filter(pk=raw, campaign_id=campaign.pk).first()
    if step is None:
        raise Http404("Campaign step not found")
    return step


def _resolve_preview(*args, **kwargs) -> preview_service.ResolvedPreview:
    try:
        return preview_service.resolve_preview(*args, **kwargs)
    except preview_service.AmbiguousPreviewStep as exc:
        raise Http404(str(exc)) from exc


def _admin_preview_denied(request, permission):
    """Staff with the model view permission, or a login redirect.

    Targets and campaign steps have sequential primary keys, so their preview
    URLs cannot be public.
    """
    user = request.user
    if not user.is_authenticated or not user.is_staff:
        return redirect_to_login(request.get_full_path())
    if not user.has_perm(permission):
        raise PermissionDenied
    return None


def _build_form(model, post_data, pk=None):
    """Bound modelform; uses pk from args, POST id/_save, or explicit pk."""
    ModelForm = modelform_factory(model, fields="__all__")
    pk = pk or post_data.get("id") or post_data.get("_save")
    if pk:
        try:
            return ModelForm(post_data, instance=model.objects.get(pk=pk))
        except model.DoesNotExist:
            pass
    return ModelForm(post_data)


def _set_field(instance, form, field_name, value, post_data):
    """Set field via widget/clean logic or raw value."""
    field = form.fields[field_name]

    if hasattr(field, "widget") and hasattr(field.widget, "value_from_datadict"):
        widget_value = field.widget.value_from_datadict(post_data, None, field_name)
        if widget_value:
            try:
                setattr(instance, field_name, field.clean(widget_value))
                return
            except (ValueError, TypeError):
                setattr(instance, field_name, widget_value)
                return

    try:
        setattr(instance, field_name, field.clean(value))
    except (ValueError, TypeError, AttributeError):
        try:
            setattr(instance, field_name, value)
        except (ValueError, TypeError):
            pass


def _populate_from_invalid_form(model, form, post_data):
    """Instance from cleaned_data + raw POST for empty fields."""
    instance = form.instance if form.instance.pk else model()
    _apply_cleaned_form_data(instance, form.cleaned_data or {})
    _apply_raw_form_data(instance, form, post_data)
    return instance


def _apply_cleaned_form_data(instance, cleaned_data):
    for field_name, value in cleaned_data.items():
        if value is not None:
            try:
                setattr(instance, field_name, value)
            except (ValueError, TypeError):
                pass


def _apply_raw_form_data(instance, form, post_data):
    for field_name in form.fields:
        value = post_data.get(field_name)
        if not value or getattr(instance, field_name, None) is not None:
            continue
        try:
            _set_field(instance, form, field_name, value, post_data)
        except (ValueError, TypeError, AttributeError):
            try:
                setattr(instance, field_name, value)
            except (ValueError, TypeError):
                pass


class PreviewView(DetailView):
    """GET preview: ``missive`` uses the saved row; ``campaign`` and ``target`` build one.

    Missive and campaign URLs stay unauthenticated: this is the "view in browser"
    link that ``processors.body.add_preview_browser`` embeds in outgoing emails.
    The unguessable UUID pk is what keeps it private. A target pk is sequential,
    so that URL requires staff and the view permission; once the target has a
    missive, it redirects to that missive's preview. Being recipient-facing, the
    missive page must stay side-effect free — it must never regenerate the
    first-document PDF of an already sent missive.
    """

    context_object_name = "missive"
    _key: str
    _resolved_preview: preview_service.ResolvedPreview
    recipient_pk: int | None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        key = kwargs.get("campaign_or_missive", "")
        model = _PREVIEW_MODEL.get(key)
        if model is None:
            raise Http404
        self._key = key
        self.model = model
        rp = kwargs.get("recipient_pk")
        if rp is not None:
            try:
                self.recipient_pk = int(rp)
            except (TypeError, ValueError):
                raise Http404
        else:
            self.recipient_pk = None

    def get(self, request, *args, **kwargs):
        denied = self._preview_denied(request)
        if denied is not None:
            return denied

        self.object = self.get_object()
        target_redirect = self._target_redirect()
        if target_redirect is not None:
            return target_redirect

        self._validate_recipient_scope()
        postal_redirect = self._postal_recipient_redirect()
        if postal_redirect is not None:
            return postal_redirect

        self._validate_recipient()
        return super().get(request, *args, **kwargs)

    def _preview_denied(self, request):
        preview_permission = {
            "target": "django_pymissive.view_campaigntarget",
            "campaign_step": "django_pymissive.view_campaignstep",
        }.get(self._key)
        if preview_permission is None:
            return None
        return _admin_preview_denied(request, preview_permission)

    def _target_redirect(self):
        if self._key == "target" and self.object.missive_id:
            return redirect(self.object.get_browser_preview_path())
        return None

    def _validate_recipient_scope(self):
        if self.recipient_pk is not None and self._key != "missive":
            raise Http404

    def _postal_recipient_redirect(self):
        if (
            self._key != "missive"
            or self.recipient_pk is not None
            or not preview_service.missive_is_postal_like(self.object)
        ):
            return None
        first = (
            MissiveRecipient.objects.filter(
                missive_id=self.object.pk,
                recipient_type=MissiveRecipientType.RECIPIENT,
            )
            .order_by("name", "pk")
            .first()
        )
        if first is None:
            return None
        return redirect(
            "django_pymissive:preview_recipient",
            campaign_or_missive="missive",
            pk=self.object.pk,
            recipient_pk=first.pk,
        )

    def _validate_recipient(self):
        if self.recipient_pk is None:
            return
        exists = MissiveRecipient.objects.filter(
            pk=self.recipient_pk,
            missive_id=self.object.pk,
            recipient_type=MissiveRecipientType.RECIPIENT,
        ).exists()
        if not exists:
            raise Http404

    def get_resolved_preview(self):
        if hasattr(self, "_resolved_preview"):
            return self._resolved_preview
        if self._key == "campaign":
            kind = (self.request.GET.get("type") or "email").lower()
            step = campaign_step_from_request(self.request, self.object)
            self._resolved_preview = _resolve_preview(
                self.object,
                preview_kind=kind,
                brand=_brand_from_request(self.request),
                campaign_step=step,
            )
        else:
            self._resolved_preview = _resolve_preview(self.object)
        return self._resolved_preview

    def get_missive_for_preview(self) -> Missive:
        return self.get_resolved_preview().missive

    def get_template_names(self):
        if not getattr(self, "object", None):
            return [DEFAULT_TEMPLATE]
        return self.get_resolved_preview().template_names

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rp = self.recipient_pk if self._key == "missive" else None
        context.update(preview_service.build_render_context(self.get_resolved_preview(), postal_recipient_pk=rp))
        return context


@method_decorator(staff_member_required, name="dispatch")
class PreviewFormView(View):
    """POST preview from admin forms (optional); same missive-based rendering as ``PreviewView``."""

    http_method_names = ("post",)

    def _get_config(self):
        key = self.kwargs.get("campaign_or_missive", "")
        model = _PREVIEW_MODEL.get(key)
        if model is None:
            raise Http404
        return key, model

    def _preview_kind_for_campaign(self, post_data) -> str:
        return (
            self.request.GET.get("type") or post_data.get("_preview_type") or post_data.get("_preview") or "email"
        ).lower()

    def _preview_kind_for_missive(self, instance, post_data) -> str:
        missive_type = getattr(instance, "missive_type", None) or post_data.get("missive_type")
        if missive_type:
            instance.missive_type = missive_type
        return (missive_type or "").lower()

    def post(self, request, *args, **kwargs):
        key, model = self._get_config()

        form = _build_form(model, request.POST, pk=request.GET.get("pk"))
        instance = (
            form.save(commit=False) if form.is_valid() else _populate_from_invalid_form(model, form, request.POST)
        )

        if key == "campaign":
            preview_kind = self._preview_kind_for_campaign(request.POST)
            step = campaign_step_from_request(request, instance)
            preview = _resolve_preview(
                instance,
                preview_kind=preview_kind,
                brand=_brand_from_request(request, request.POST),
                campaign_step=step,
            )
        else:
            if isinstance(instance, Missive):
                instance._ensure_missive_defaults()
            self._preview_kind_for_missive(instance, request.POST)
            preview = _resolve_preview(instance)

        context = preview_service.build_render_context(preview, post_data=request.POST)
        return TemplateResponse(request, preview.template_names, context)


@method_decorator(staff_member_required, name="dispatch")
class DownloadPDFView(DetailView):
    """Download the compiled body as a PDF file."""

    _key: str
    recipient_pk: int | None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        key = kwargs.get("campaign_or_missive", "")
        model = _PREVIEW_MODEL.get(key)
        if model is None:
            raise Http404
        self._key = key
        self.model = model
        rp = kwargs.get("recipient_pk")
        if rp is not None:
            try:
                self.recipient_pk = int(rp)
            except (TypeError, ValueError):
                raise Http404
            if self._key != "missive":
                raise Http404
        else:
            self.recipient_pk = None

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()

        if self._key == "missive":
            preview = _resolve_preview(self.object)
            rp = self.recipient_pk
            if rp is not None:
                ok = MissiveRecipient.objects.filter(
                    pk=rp,
                    missive_id=self.object.pk,
                    recipient_type=MissiveRecipientType.RECIPIENT,
                ).exists()
                if not ok:
                    raise Http404
            elif preview_service.missive_is_postal_like(self.object):
                first = (
                    MissiveRecipient.objects.filter(
                        missive_id=self.object.pk,
                        recipient_type=MissiveRecipientType.RECIPIENT,
                    )
                    .order_by("name", "pk")
                    .first()
                )
                rp = first.pk if first else None
            else:
                rp = None
            pdf_bytes = preview.missive.body_to_pdf(postal_recipient_pk=rp)
            filename = f"missive-{self.object.pk}.pdf"
        elif self._key == "campaign_step":
            preview = _resolve_preview(self.object)
            pdf_bytes = preview.missive.body_to_pdf(postal_recipient_pk=None)
            filename = f"campaign-step-{self.object.pk}.pdf"
        else:
            if self.recipient_pk is not None:
                raise Http404
            preview_kind = (request.GET.get("type") or "postal").lower()
            step = campaign_step_from_request(request, self.object)
            preview = _resolve_preview(self.object, preview_kind=preview_kind, campaign_step=step)
            pdf_bytes = preview.missive.body_to_pdf(postal_recipient_pk=None)
            filename = f"campaign-{self.object.pk}.pdf"

        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
