"""Builds one concrete AI provider from its route name (`claude_cli`, `gemini_api`, ...)."""
from __future__ import annotations
from videocreator.ai.base import AIError, AIProvider, AIRole
from videocreator.ai.claude import ClaudeAPIProvider
from videocreator.ai.claude_cli import ClaudeCLIProvider
from videocreator.ai.gemini import GeminiAPIProvider
from videocreator.ai.muse_api import MuseAPIProvider
from videocreator.ai.muse_gateway_chat import MuseGatewayChatProvider
from videocreator.config import Settings
from videocreator.paths import AppPaths
from videocreator.secrets_store import SecretsStore


def build_single_provider(
    provider_name: str,
    paths: AppPaths,
    settings: Settings,
    secrets_store: SecretsStore | None = None,
    *,
    role: AIRole = "writer",
) -> AIProvider:
    """Instantiates a concrete `AIProvider` by name and role."""
    secrets = secrets_store or SecretsStore(paths.secrets_file)
    if provider_name == "claude_cli":
        cli_model = "haiku" if role == "checker" else "sonnet"
        return ClaudeCLIProvider(paths.db_file, role=role, model=cli_model)
    if provider_name == "gemini_api":
        return GeminiAPIProvider(
            paths.db_file,
            paths.config_file,
            secrets,
            role=role,
            model=settings.ai.gemini_model,
        )
    if provider_name == "claude_api":
        if role == "checker":
            model = settings.ai.claude_checker_model
        elif role == "studio":
            model = settings.studio.model
        else:
            model = settings.ai.claude_writer_model
        return ClaudeAPIProvider(
            paths.db_file,
            paths.config_file,
            secrets,
            role=role,
            model=model,
        )
    if provider_name == "muse_api":
        return MuseAPIProvider(
            paths.db_file,
            paths.config_file,
            secrets,
            role=role,
            model="Muse-Spark",
        )
    if provider_name == "muse_gateway":
        return MuseGatewayChatProvider(
            paths.db_file,
            paths.config_file,
            secrets,
            role=role,
            model="muse-chat",
        )
    raise AIError(f"Unknown or unsupported AI provider '{provider_name}'")
