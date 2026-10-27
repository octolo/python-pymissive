from django import template
from django.templatetags.static import static
from django.utils.html import format_html, json_script
from django.utils.translation import gettext as _
from django.utils.translation import pgettext

register = template.Library()

_CSS = "django_pymissive/css/animations.css"
_JS = "django_pymissive/js/animation.js"
_LABELS_ID = "pymissive-animation-labels"


def animation_labels() -> dict:
    """Texts of animation.js in the active language, keyed like its ``DEFAULT_LABELS``."""
    return {
        "email.title": _("Email"),
        "email.subtitle": _("An email arrives in an inbox"),
        "emailAR.title": _("Email with AR"),
        "emailAR.subtitle": _("Read or delivery confirmation"),
        "postal.title": _("Postal mail"),
        "postal.subtitle": _("Envelopes arrive in the mailbox"),
        "registered.title": _("Registered mail with AR"),
        "registered.subtitle": _("Tracked envelope and proof of delivery"),
        "handDelivery.title": _("Hand delivery"),
        "handDelivery.subtitle": _("The letter is handed over against signature"),
        "sms.title": _("SMS"),
        "sms.subtitle": _("Messages arrive on the phone"),
        "voice.title": _("Voice call"),
        "voice.subtitle": _("A call arrives on the phone"),
        "notification.title": _("Notification"),
        "notification.subtitle": _("A notification arrives on the phone"),
        "receiver.email": _("Screen — Email"),
        "receiver.emailAR": _("Screen — Email with AR"),
        "receiver.mailbox": _("Mailbox"),
        "receiver.mailboxAR": _("Mailbox with AR"),
        "receiver.doorstep": _("Door — Hand delivery"),
        "receiver.sms": _("Phone — SMS"),
        "receiver.voice": _("Phone — Voice call"),
        "receiver.notification": _("Phone — Notification"),
        "receiver.globe": _("Globe"),
        "scene.arMark": _("AR"),
        "scene.receiptTitle": _("Email received"),
        "scene.receiptText": _("Confirmation sent"),
        "scene.smsSample": _("Hi! 👋"),
        "scene.smsApp": _("Messages"),
        "scene.smsReceived": _("Hello!"),
        "scene.smsSent": _("How are you?"),
        "scene.incomingCall": _("Incoming call"),
        "scene.voiceMessage": _("Voice"),
        "scene.noticeTitle": _("Notification"),
        "scene.noticeText": _("New message"),
        "scene.receiptStamp": _("RECEIPT ACKNOWLEDGED"),
        "scene.handedStamp": _("HANDED OVER"),
        "combination.subtitle": _("Custom combination"),
        "combination.aria": _("Preview of the send to the selected receiver"),
        "counter.aria": _("Send progress counter"),
        "counter.progressAria": _("Send progress"),
        "counter.remaining": _("remaining"),
        "counter.processed": _("processed"),
        "counter.sentOne": pgettext("one send", "sent"),
        "counter.sentMany": pgettext("several sends", "sent"),
        "counter.errorOne": _("error"),
        "counter.errorMany": _("errors"),
        "counter.summaryTitle": _("{sent} sent, {errors} errors out of {total}"),
        "counter.totalTitle": _("{total} sends in total"),
    }


@register.simple_tag
def pymissive_animations_css():
    """Stylesheet for the communication animations. Place this tag in the document head."""
    return format_html(
        '<link rel="stylesheet" href="{}" data-pymissive-animations>',
        static(_CSS),
    )


@register.simple_tag
def pymissive_animations_js():
    """Script that runs the communication animations already present in the page."""
    return format_html(
        '<script src="{}" data-pymissive-animations></script>',
        static(_JS),
    )


@register.simple_tag
def pymissive_animations_labels():
    """Translated texts for animation.js, read by the script on first mount."""
    return json_script(animation_labels(), _LABELS_ID)


@register.simple_tag
def pymissive_animations_assets():
    """Stylesheet, script and translated texts for the communication animations."""
    return format_html(
        "{}{}{}",
        pymissive_animations_css(),
        pymissive_animations_labels(),
        pymissive_animations_js(),
    )
