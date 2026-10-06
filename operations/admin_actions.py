"""Admin actions that confirm intent, require a reason and call a service."""

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.template.response import TemplateResponse

from .services import OperationError


class ReasonForm(forms.Form):
    reason = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3, "cols": 70}),
        max_length=500,
        help_text="Recorded in the audit log. Where relevant it is shown to the affected user.",
    )


class RefundForm(ReasonForm):
    restock = forms.BooleanField(
        required=False,
        label="Return the items to the vendor's stock",
        help_text="Tick this if the buyer never collected the items.",
    )


def confirmed_action(*, name, label, permission, service, consequences, reversible,
                     submit_label, form_class=ReasonForm):
    """Build an admin action that shows a confirmation page before running
    ``service(obj, actor=..., reason=..., request=..., **extra)`` per object.

    ``permission`` is a ModelAdmin permission suffix: the ModelAdmin must
    define ``has_<permission>_permission(request)``.
    """

    def action(modeladmin, request, queryset):
        if request.POST.get("apply"):
            form = form_class(request.POST)
            if form.is_valid():
                extra = {key: value for key, value in form.cleaned_data.items() if key != "reason"}
                done = 0
                for obj in queryset:
                    try:
                        service(obj, actor=request.user, reason=form.cleaned_data["reason"],
                                request=request, **extra)
                        done += 1
                    except OperationError as exc:
                        modeladmin.message_user(request, f"{obj}: {exc.message}", messages.ERROR)
                if done:
                    modeladmin.message_user(request, f"{label}: done for {done} item{'s' if done != 1 else ''}.",
                                            messages.SUCCESS)
                return None
        else:
            form = form_class()
        return TemplateResponse(request, "admin/operations/confirm_action.html", {
            **modeladmin.admin_site.each_context(request),
            "title": label,
            "opts": modeladmin.model._meta,
            "queryset": queryset,
            "form": form,
            "action_name": name,
            "action_checkbox_name": ACTION_CHECKBOX_NAME,
            "consequences": consequences,
            "reversible": reversible,
            "submit_label": submit_label,
        })

    action.__name__ = name
    return admin.action(description=label, permissions=[permission])(action)


def simple_action(*, name, label, permission, service):
    """Low-risk action without a confirmation page (e.g. featuring a listing)."""

    def action(modeladmin, request, queryset):
        done = 0
        for obj in queryset:
            try:
                service(obj, actor=request.user, request=request)
                done += 1
            except OperationError as exc:
                modeladmin.message_user(request, f"{obj}: {exc.message}", messages.ERROR)
        if done:
            modeladmin.message_user(request, f"{label}: done for {done} item{'s' if done != 1 else ''}.",
                                    messages.SUCCESS)

    action.__name__ = name
    return admin.action(description=label, permissions=[permission])(action)
