from .base import Budgeted, BudgetExceeded, NotSupported, Provider, Role, Usage
from .mock import MockProvider


def make_provider(name: str, models: dict[str, str] | None = None) -> Provider:
    if name == "mock":
        return MockProvider()
    if name == "claude-cli":
        from .cli_agents import ClaudeCLI
        return ClaudeCLI(models)
    if name == "codex-cli":
        from .cli_agents import CodexCLI
        return CodexCLI(models)
    if name == "anthropic":
        from .anthropic_api import AnthropicAPI
        return AnthropicAPI(models)
    raise ValueError(f"unknown provider {name!r} (mock|claude-cli|codex-cli|anthropic)")


__all__ = ["Budgeted", "BudgetExceeded", "NotSupported", "Provider", "Role", "Usage", "MockProvider", "make_provider"]
