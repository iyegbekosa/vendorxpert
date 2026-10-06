from rest_framework.throttling import AnonRateThrottle


class SignupRateThrottle(AnonRateThrottle):
    scope = "signup"


class LoginRateThrottle(AnonRateThrottle):
    scope = "login"


class PasswordResetRateThrottle(AnonRateThrottle):
    scope = "password_reset"


class OTPVerifyRateThrottle(AnonRateThrottle):
    """Limits code guessing per IP; codes also lock after a few wrong tries."""

    scope = "otp_verify"


class OTPResendRateThrottle(AnonRateThrottle):
    """Stops the resend endpoint being used to flood someone's inbox."""

    scope = "otp_resend"
