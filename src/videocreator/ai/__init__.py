"""Public entry point for obtaining a role-based AIProvider (Phase 04 & Phase 18)."""
from __future__ import annotations

from videocreator.ai.base import (
    AIError,
    AIProvider,
    AIRole,
    BudgetExceeded,
    ProviderAuthError,
    ProviderQuotaExhausted,
    SchemaValidationError,
)
from videocreator.ai.router import RoutedProvider
from videocreator.paths import AppPaths
from videocreator.secrets_store import SecretsStore

__all__ = [
    "AIError",
    "AIProvider",
    "AIRole",
    "BudgetExceeded",
    "ProviderAuthError",
    "ProviderQuotaExhausted",
    "RoutedProvider",
    "SchemaValidationError",
    "get_provider",
]


def get_provider(
    paths: AppPaths,
    role: AIRole,
    *,
    secrets_store: SecretsStore | None = None,
    provider_overrides: dict[str, AIProvider] | None = None,
    allow_api_fallback: bool = False,
) -> RoutedProvider:
    """Returns a `RoutedProvider` configured for `role` (`vision`, `writer`, `checker`, `studio`)."""
    return RoutedProvider(
        paths,
        role,
        secrets_store=secrets_store,
        provider_overrides=provider_overrides,
        allow_api_fallback=allow_api_fallback,
    )
