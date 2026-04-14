from __future__ import annotations

from provider_adoption_data.models import ProviderConfig, ProviderPackageConfig


PROVIDER_REGISTRY: tuple[ProviderConfig, ...] = (
    ProviderConfig(
        slug="openai",
        display_name="OpenAI",
        enabled=True,
        pypi_packages=(ProviderPackageConfig("openai", "sdk"),),
        npm_packages=(
            ProviderPackageConfig("openai", "sdk", "core_sdk"),
            ProviderPackageConfig("@openai/agents", "sdk", "agent_sdk"),
            ProviderPackageConfig("@openai/codex", "cli", "cli"),
            ProviderPackageConfig("@openai/codex-sdk", "sdk", "agent_sdk"),
        ),
        manifest_patterns=("openai",),
        import_patterns=(
            "from openai import",
            "import openai",
            "from \"openai\"",
            "from 'openai'",
            "require(\"openai\")",
            "require('openai')",
        ),
        env_var_patterns=("OPENAI_API_KEY",),
        model_patterns=("gpt-4.1", "gpt-4o", "gpt-4o-mini", "o3", "o4-mini"),
    ),
    ProviderConfig(
        slug="anthropic",
        display_name="Anthropic",
        enabled=True,
        pypi_packages=(ProviderPackageConfig("anthropic", "sdk"),),
        npm_packages=(
            ProviderPackageConfig("@anthropic-ai/sdk", "sdk", "core_sdk"),
            ProviderPackageConfig("@anthropic-ai/claude-agent-sdk", "sdk", "agent_sdk"),
            ProviderPackageConfig("@anthropic-ai/claude-code", "cli", "cli"),
        ),
        manifest_patterns=("anthropic", "@anthropic-ai/sdk"),
        import_patterns=(
            "from anthropic import",
            "import anthropic",
            "@anthropic-ai/sdk",
        ),
        env_var_patterns=("ANTHROPIC_API_KEY",),
        model_patterns=("claude-3-5-sonnet", "claude-3-7-sonnet", "claude-sonnet-4", "claude-opus-4"),
    ),
    ProviderConfig(
        slug="google",
        display_name="Google",
        enabled=True,
        pypi_packages=(
            ProviderPackageConfig("google-genai", "sdk"),
            ProviderPackageConfig("google-generativeai", "legacy_sdk"),
        ),
        npm_packages=(
            ProviderPackageConfig("@google/genai", "sdk", "core_sdk"),
            ProviderPackageConfig("@google/gemini-cli", "cli", "cli"),
            ProviderPackageConfig("@google/generative-ai", "sdk", "legacy_sdk"),
        ),
        manifest_patterns=("google-genai", "google-generativeai", "@google/genai", "@google/generative-ai"),
        import_patterns=(
            "from google import genai",
            "import google.generativeai",
            "@google/genai",
            "@google/generative-ai",
        ),
        env_var_patterns=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        model_patterns=("gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-pro"),
    ),
    ProviderConfig(
        slug="qwen",
        display_name="Qwen",
        enabled=False,
        pypi_packages=(ProviderPackageConfig("dashscope", "sdk"),),
        npm_packages=(),
        manifest_patterns=("dashscope",),
        import_patterns=("import dashscope", "from dashscope import"),
        env_var_patterns=("DASHSCOPE_API_KEY",),
        model_patterns=("qwen2.5", "qwen-max", "qwen-plus", "qwen-turbo"),
    ),
)


def get_provider_registry(provider_slugs: list[str] | None = None) -> tuple[ProviderConfig, ...]:
    active = [provider for provider in PROVIDER_REGISTRY if provider.enabled]
    if provider_slugs:
        wanted = {slug.strip().lower() for slug in provider_slugs if slug.strip()}
        active = [provider for provider in active if provider.slug in wanted]
    return tuple(active)
