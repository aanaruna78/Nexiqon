"""Provider-neutral request/response types (the model port's contract)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Role = Literal["system", "user", "assistant", "tool"]
Classification = Literal["public", "internal", "confidential", "restricted"]


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class Message(BaseModel):
    role: Role
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None


class ToolSpec(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class ChatCall(BaseModel):
    """What an adapter receives: model settings already chosen by the gateway."""

    model: str
    base_url: str | None = None
    messages: list[Message]
    tools: list[ToolSpec] = Field(default_factory=list)
    response_schema: dict[str, Any] | None = None
    json_schema_supported: bool = True
    max_tokens: int = 1024
    temperature: float | None = None


class ChatOutput(BaseModel):
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: str = "stop"
    usage: Usage = Field(default_factory=Usage)
    model: str


class EmbedCall(BaseModel):
    model: str
    base_url: str | None = None
    inputs: list[str]
    dimensions: int
    input_type: Literal["document", "query"] = "document"


class EmbedOutput(BaseModel):
    vectors: list[list[float]]
    usage: Usage = Field(default_factory=Usage)
    model: str


class RerankCall(BaseModel):
    model: str
    base_url: str | None = None
    query: str
    documents: list[str]
    top_n: int


class RerankOutput(BaseModel):
    results: list[tuple[int, float]]  # (document index, relevance score), best first
    model: str
