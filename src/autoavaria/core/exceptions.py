class AutoAvariaError(Exception):
    """Base exception for AutoAvaria domain errors."""


class ConfigurationError(AutoAvariaError):
    """Raised when application configuration is invalid."""
