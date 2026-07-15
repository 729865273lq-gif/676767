import pytest

from app.agents.base.registry import AgentAlreadyRegistered, AgentNotFound, AgentRegistry


class ExampleAgent:
    agent_id = "example"
    version = "1.0.0"


def test_registry_resolves_registered_agent_without_switch_statement() -> None:
    registry = AgentRegistry()
    registry.register(ExampleAgent())

    assert registry.resolve("example").version == "1.0.0"


def test_registry_rejects_duplicate_ids_and_unknown_agents() -> None:
    registry = AgentRegistry()
    registry.register(ExampleAgent())

    with pytest.raises(AgentAlreadyRegistered):
        registry.register(ExampleAgent())
    with pytest.raises(AgentNotFound):
        registry.resolve("missing")
