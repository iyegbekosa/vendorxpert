from rest_framework.throttling import AnonRateThrottle


class SignupRateThrottle(AnonRateThrottle):
    """5 signup attempts per hour per IP."""
    scope = "signup"


class LoginRateThrottle(AnonRateThrottle):
    """10 login attempts per hour per IP."""
    scope = "login"


class PasswordResetRateThrottle(AnonRateThrottle):
    """5 password reset requests per hour per IP."""
    scope = "password_reset"
