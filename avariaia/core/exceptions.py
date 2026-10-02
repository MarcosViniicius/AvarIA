class AvarIAError(Exception):
    """Base exception for AvarIA domain errors."""


# Compatibilidade com o nome antigo (rebrand 2026-10): qualquer import
# existente de `AutoAvariaError` continua funcionando.
AutoAvariaError = AvarIAError


class ConfigurationError(AvarIAError):
    """Raised when application configuration is invalid."""
