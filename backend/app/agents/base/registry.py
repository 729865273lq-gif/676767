from __future__ import annotations

from app.agents.base.contracts import Agent


class AgentAlreadyRegistered(ValueError):
    """Raised when an agent identifier is registered twice."""


class AgentNotFound(LookupError):
    """Raised when an enabled agent cannot be resolved."""


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    def register(self, agent: Agent) -> None:
        if agent.agent_id in self._agents:
            raise AgentAlreadyRegistered(f"agent already registered: {agent.agent_id}")
        self._agents[agent.agent_id] = agent

    def resolve(self, agent_id: str) -> Agent:
        try:
            return self._agents[agent_id]
        except KeyError as error:
            raise AgentNotFound(f"agent not found: {agent_id}") from error
