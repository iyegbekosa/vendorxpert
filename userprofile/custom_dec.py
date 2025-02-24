from django.contrib.auth.decorators import user_passes_test

def vendor_required(view_func):
    """
    Decorator to restrict access to vendor-only views.
    """
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_vendor:
            from django.http import HttpResponseForbidden
            return HttpResponseForbidden("You must be a vendor to access this page.")
        return view_func(request, *args, **kwargs)
    return _wrapped_view
