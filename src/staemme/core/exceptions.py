"""Custom exceptions for the Staemme bot."""

from __future__ import annotations


class StaemmeError(Exception):
    """Base exception for all bot errors."""


class SessionExpiredError(StaemmeError):
    """Raised when the game session has expired and needs re-login."""


class CaptchaRequiredError(StaemmeError):
    """Raised when a captcha must be solved."""


class CSRFTokenError(StaemmeError):
    """Raised when the CSRF token is missing or invalid."""


class BuildQueueFullError(StaemmeError):
    """Raised when the building queue is at capacity."""


class InsufficientResourcesError(StaemmeError):
    """Raised when resources are not enough for an action."""


class InsufficientTroopsError(StaemmeError):
    """Raised when not enough troops are available."""


class IncomingAttackError(StaemmeError):
    """Raised when an incoming attack is detected."""


class RateLimitError(StaemmeError):
    """Raised when the server returns a rate-limit response."""


class ExtractionError(StaemmeError):
    """Raised when game data cannot be extracted from a page."""


class BotProtectionDetectedError(StaemmeError):
    """Raised when bot protection indicator is detected on the page."""
