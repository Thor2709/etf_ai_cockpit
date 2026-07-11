from __future__ import annotations


class CockpitError(Exception):
    """Base exception for expected cockpit errors."""


class ConfigError(CockpitError):
    """Raised when a config file fails validation."""


class DataQualityError(CockpitError):
    """Raised when data cannot be used safely."""


class AuditImportError(CockpitError):
    """Raised when a ChatGPT audit import is invalid."""


class StoreValidationError(CockpitError):
    """Raised when a replacement store fails pre-commit validation."""
