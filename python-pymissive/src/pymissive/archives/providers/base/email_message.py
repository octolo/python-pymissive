"""Shared helpers for constructing email messages with attachments."""

from __future__ import annotations

from email.message import EmailMessage
from typing import Any, Dict, Iterable, List


def _collect_email_attachments(provider: Any) -> List[Dict[str, Any]]:
    """Gather attachment payloads from the current missive context."""
    attachments: List[Dict[str, Any]] = []
    source = provider._get_missive_value("attachments") or getattr(
        provider.missive, "attachments", None
    )
    if not source:
        return attachments

    if hasattr(source, "all"):
        iterable: Iterable[Any] = source.all()  # type: ignore[assignment]
    elif isinstance(source, Iterable):
        iterable = source
    else:
        iterable = []

    for attachment in iterable:
        try:
            payload = provider.add_attachment_email(attachment)
        except Exception:
            continue
        attachments.append(payload)
    return attachments


def _set_message_body(message: EmailMessage, body_text: str, body_html: str) -> None:
    """Populate an EmailMessage with text and optional HTML versions."""
    if body_text:
        message.set_content(body_text)
    else:
        # Avoid empty payloads (SMTP servers sometimes reject them).
        message.set_content(" ")
    if body_html and body_html != body_text:
        message.add_alternative(body_html, subtype="html")


def _attach_files(message: EmailMessage, attachments: List[Dict[str, Any]]) -> None:
    """Attach files to the EmailMessage."""
    for attachment in attachments:
        content = attachment.get("content")
        if not content:
            continue
        filename = attachment.get("filename") or "attachment"
        mime = attachment.get("mime_type") or "application/octet-stream"
        maintype, _, subtype = mime.partition("/")
        subtype = subtype or "octet-stream"
        message.add_attachment(
            content,
            maintype=maintype,
            subtype=subtype,
            filename=filename,
        )


def build_email_message(
    provider: Any, recipient: str, *, from_email: str
) -> EmailMessage:
    """Create a ready-to-send EmailMessage for the given recipient."""
    subject = str(provider._get_missive_value("subject") or "Missive")
    body_html = provider._get_missive_value("body") or ""
    body_text = provider._get_missive_value("body_text") or (
        body_html if body_html and "<" not in body_html else ""
    )

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_email
    message["To"] = recipient

    _set_message_body(message, body_text, body_html)
    attachments = _collect_email_attachments(provider)
    _attach_files(message, attachments)

    return message


__all__ = ["build_email_message"]
