"""OpenAI-compatible chat/embeddings client (vLLM, LiteLLM proxy, Ollama, TGI) + scripted fake for tests."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMReply:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLM(Protocol):
    async def chat(self, messages: list[dict], tools: list[dict] | None = None, json_mode: bool = False) -> LLMReply: ...
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAICompatibleLLM:
    def __init__(self, base_url: str | None = None, model: str | None = None, api_key: str | None = None,
                 embed_model: str | None = None, client: httpx.AsyncClient | None = None):
        self.base_url = (base_url or os.environ.get("OMNILINK_LLM_URL", "http://vllm:8000/v1")).rstrip("/")
        self.model = model or os.environ.get("OMNILINK_LLM_MODEL", "Qwen/Qwen2.5-32B-Instruct-AWQ")
        self.embed_model = embed_model or os.environ.get("OMNILINK_EMBED_MODEL", "BAAI/bge-m3")
        self.embed_url = os.environ.get("OMNILINK_EMBED_URL", self.base_url).rstrip("/")
        self.headers = {"Authorization": f"Bearer {api_key or os.environ.get('OMNILINK_LLM_KEY', 'none')}"}
        self.client = client or httpx.AsyncClient(timeout=120)

    async def chat(self, messages, tools=None, json_mode=False) -> LLMReply:
        body: dict[str, Any] = {"model": self.model, "messages": messages, "temperature": 0.1, "max_tokens": 1500}
        if tools:
            body["tools"], body["tool_choice"] = tools, "auto"
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        r = await self.client.post(f"{self.base_url}/chat/completions", json=body, headers=self.headers)
        r.raise_for_status()
        msg = r.json()["choices"][0]["message"]
        calls = []
        for tc in msg.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"_invalid_json": tc["function"].get("arguments")}
            calls.append(ToolCall(tc["id"], tc["function"]["name"], args))
        return LLMReply(msg.get("content"), calls)

    async def embed(self, texts):
        r = await self.client.post(f"{self.embed_url}/embeddings", json={"model": self.embed_model, "input": texts},
                                   headers=self.headers)
        r.raise_for_status()
        return [d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"])]


class ScriptedLLM:
    """Deterministic LLM for tests: returns queued replies; embeds by hashing character trigrams."""

    def __init__(self, replies: list[LLMReply] | None = None):
        self.replies = list(replies or [])
        self.seen: list[list[dict]] = []
        self.tools_offered: list[list[str]] = []

    async def chat(self, messages, tools=None, json_mode=False):
        self.seen.append(messages)
        self.tools_offered.append([t["function"]["name"] for t in tools or []])
        return self.replies.pop(0) if self.replies else LLMReply("(no more scripted replies)")

    async def embed(self, texts):
        out = []
        for t in texts:
            v = [0.0] * 64
            s = t.lower()
            for i in range(len(s) - 2):
                v[hash(s[i:i + 3]) % 64] += 1.0
            out.append(v)
        return out
