from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class AgentRunContext:
    organization_id: str
    workflow_run_id: str


class SearchResult(BaseModel):
    url: str
    title: str
    snippet: str = ""
    canonical_key: str = ""
    email: str = ""
    phone: str = ""
    whatsapp: str = ""
    social_profiles: list[dict[str, str]] = Field(default_factory=list)
    source_url: str = ""


class OutboundMessage(BaseModel):
    recipients: list[str] = Field(min_length=1)
    subject: str
    body: str


class InboundMessage(BaseModel):
    provider_message_id: str
    provider_thread_id: str | None = None
    sender: str
    recipients: list[str]
    subject: str
    body: str


class RetrievedChunk(BaseModel):
    document_id: str
    text: str
    source_reference: str


class LlmCompletion(BaseModel):
    content: str
    model: str


class Agent(Protocol):
    agent_id: str
    version: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]

    async def run(self, context: AgentRunContext, payload: BaseModel) -> BaseModel: ...
