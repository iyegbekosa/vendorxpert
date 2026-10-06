"""Writing the audit trail for privileged actions."""

from .models import AuditLog


def _client_ip(request):
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (forwarded.split(",")[0].strip() or request.META.get("REMOTE_ADDR")) or None


def record(*, actor, action, target, reason="", changes=None, request=None):
    """Append an audit entry. ``target`` is any model instance."""
    return AuditLog.objects.create(
        actor=actor if getattr(actor, "pk", None) else None,
        actor_label=getattr(actor, "email", "") or "system",
        action=action,
        target_type=target._meta.label,
        target_id=str(target.pk),
        target_label=str(target)[:255],
        reason=reason,
        changes=changes or {},
        ip_address=_client_ip(request),
    )
