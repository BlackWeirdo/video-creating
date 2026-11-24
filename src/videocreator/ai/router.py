"""Subscription-first AI provider router with quota cooldown and API fallback policies (Phase 04 & 18)."""
from __future__ import annotations

import logging
from pathlib import Path

from videocreator.ai.base import (
    AIError,
    AIProvider,
    AIRole,
    BudgetExceeded,
    ProviderAuthError,
    ProviderQuotaExhausted,
    RouteKind,
    T,
)
from videocreator.ai.providers import build_single_provider
from videocreator.ai.quota import (
    clear_provider_rest,
    earliest_recovery_seconds,
    is_provider_resting,
    mark_provider_error,
    mark_provider_resting,
)
from videocreator.config import Settings, load_settings
from videocreator.jobs import QuotaWaitRequested
from videocreator.paths import AppPaths
from videocreator.secrets_store import SecretsStore

logger = logging.getLogger("videocreator.ai.router")


class RoutedProvider:
    """Routes `describe_video` and `generate_json` calls across configured providers for `role`."""

    name: str = "routed"
    route_kind: RouteKind = "subscription"

    def __init__(
        self,
        paths: AppPaths,
        role: AIRole,
        *,
        secrets_store: SecretsStore | None = None,
        provider_overrides: dict[str, AIProvider] | None = None,
        allow_api_fallback: bool = False,
    ) -> None:
        self.paths = paths
        self.role: AIRole = role
        self.secrets_store = secrets_store
        self.provider_overrides = provider_overrides or {}
        self.allow_api_fallback = allow_api_fallback
        self.last_used_provider: str | None = None

    def _route_list(self, settings: Settings) -> list[str]:
        routes = settings.ai.routes
        if self.role == "vision":
            return list(routes.vision)
        if self.role == "writer":
            return list(routes.writer)
        if self.role == "checker":
            return list(routes.checker)
        if self.role == "studio":
            return list(routes.studio)
        if self.role == "translator":
            return list(routes.translator)
        return list(routes.writer)

    def _resolve_provider(self, pname: str, settings: Settings) -> AIProvider:
        if pname in self.provider_overrides:
            return self.provider_overrides[pname]
        return build_single_provider(
            pname,
            self.paths,
            settings,
            self.secrets_store,
            role=self.role,
        )

    def _execute(self, call_fn):  # type: ignore[no-untyped-def]
        settings = load_settings(self.paths.config_file)
        provider_names = self._route_list(settings)
        if not provider_names:
            raise AIError(f"No AI providers configured for role '{self.role}'")

        policy = settings.ai.policy.api_fallback
        resting_sub_providers: list[str] = []
        last_error: Exception | None = None

        for pname in provider_names:
            provider = self._resolve_provider(pname, settings)
            resting, until_ts = is_provider_resting(self.paths.db_file, pname)
            if resting:
                logger.info(
                    "Skipping resting provider '%s' for role '%s' (resting until %s)",
                    pname,
                    self.role,
                    until_ts,
                )
                if provider.route_kind == "subscription":
                    resting_sub_providers.append(pname)
                continue

            # Enforce subscription-first policy before falling back to paid API
            if provider.route_kind == "api":
                if policy == "never":
                    logger.info(
                        "Skipping paid API provider '%s' because api_fallback='never'",
                        pname,
                    )
                    continue
                if (
                    policy == "ask"
                    and resting_sub_providers
                    and not self.allow_api_fallback
                ):
                    wait_s = earliest_recovery_seconds(
                        self.paths.db_file, resting_sub_providers
                    )
                    raise QuotaWaitRequested(
                        reason=(
                            f"Subscription provider ({', '.join(resting_sub_providers)}) "
                            f"is out of quota and api_fallback='ask'. Waiting for quota recovery or user approval."
                        ),
                        retry_after_s=wait_s,
                    )

            try:
                result = call_fn(provider)
                clear_provider_rest(self.paths.db_file, pname)
                self.last_used_provider = pname
                self.route_kind = provider.route_kind
                return result
            except BudgetExceeded:
                raise
            except ProviderQuotaExhausted as exc:
                mark_provider_resting(
                    self.paths.db_file,
                    pname,
                    duration_s=exc.retry_after_s,
                    error_msg=str(exc),
                )
                if provider.route_kind == "subscription":
                    resting_sub_providers.append(pname)
                last_error = exc
                logger.warning(
                    "Provider '%s' hit quota limit (%s); marked resting for %ds",
                    pname,
                    exc,
                    exc.retry_after_s,
                )
                continue
            except ProviderAuthError as exc:
                mark_provider_error(self.paths.db_file, pname, str(exc))
                last_error = exc
                logger.warning("Provider '%s' auth error: %s", pname, exc)
                continue
            except Exception as exc:
                mark_provider_error(self.paths.db_file, pname, str(exc))
                last_error = exc
                logger.warning("Provider '%s' failed for role '%s': %s", pname, self.role, exc)
                continue

        if resting_sub_providers:
            wait_s = earliest_recovery_seconds(
                self.paths.db_file, resting_sub_providers
            )
            raise QuotaWaitRequested(
                reason=(
                    f"All available subscription providers ({', '.join(resting_sub_providers)}) "
                    f"are resting due to quota limits (policy={policy})."
                ),
                retry_after_s=wait_s,
            )

        if last_error is not None:
            if isinstance(last_error, AIError):
                raise last_error
            raise AIError(str(last_error)) from last_error

        raise AIError(
            f"No eligible AI provider could run for role '{self.role}' (policy={policy})"
        )

    def describe_video(
        self,
        video: Path,
        prompt: str,
        schema: type[T],
        *,
        thumbnails: list[Path] | None = None,
    ) -> T:
        return self._execute(
            lambda prov: prov.describe_video(
                video, prompt, schema, thumbnails=thumbnails
            )
        )

    def generate_json(self, prompt: str, schema: type[T]) -> T:
        return self._execute(lambda prov: prov.generate_json(prompt, schema))
