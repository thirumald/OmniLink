"""Assistant API service (FastAPI). Mounted behind APISIX at /v1/assistant."""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import Depends, HTTPException, Request
from omnilink_services.common import Principal, create_app, require
from pydantic import BaseModel, Field

from .agent import Agent
from .llm import LLM, OpenAICompatibleLLM
from .platform import PlatformClient
from .rag import MemoryKnowledgeBase
from .tools import ToolContext
from .triage import triage
from .workflow_gen import FlowValidationError, draft_flow


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    session_id: str | None = None


class DraftIn(BaseModel):
    request: str = Field(min_length=5, max_length=2000)


class KnowledgeIn(BaseModel):
    doc: str
    text: str = Field(max_length=2_000_000)
    meta: dict[str, Any] = Field(default_factory=dict)


def build_app(llm: LLM | None = None, http: httpx.AsyncClient | None = None, kb: MemoryKnowledgeBase | None = None):
    llm = llm or OpenAICompatibleLLM()
    kb = kb or MemoryKnowledgeBase(llm)
    agent = Agent(llm)
    app = create_app("assistant", "OmniLink AI Assistant")
    app.state.agent, app.state.kb = agent, kb

    def ctx_for(request: Request, p: Principal) -> ToolContext:
        token = request.headers.get("authorization", "Bearer dev").split(" ", 1)[-1]
        dev = {k: v for k, v in request.headers.items() if k in ("x-user", "x-tenant", "x-roles")} \
            if os.environ.get("OMNILINK_AUTH_MODE") == "dev" else None
        return ToolContext(p.tenant, p.username or p.sub, p.roles, PlatformClient(token, client=http, dev_headers=dev), kb)

    @app.post("/v1/assistant/chat")
    async def chat(body: ChatIn, request: Request, p: Principal = Depends(require("viewer"))):
        res = await agent.chat(ctx_for(request, p), body.message, body.session_id)
        return {"session_id": res.session_id, "answer": res.answer, "trace": res.trace,
                "pending_actions": [vars(a) for a in res.pending_actions]}

    async def _decide(action_id: str, approve: bool, request: Request, p: Principal):
        try:
            pa = await agent.decide(ctx_for(request, p), action_id, approve)
        except KeyError as exc:
            raise HTTPException(404, "action not found") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        return vars(pa)

    @app.post("/v1/assistant/actions/{action_id}/approve")
    async def approve(action_id: str, request: Request, p: Principal = Depends(require("operator"))):
        return await _decide(action_id, True, request, p)

    @app.post("/v1/assistant/actions/{action_id}/reject")
    async def reject(action_id: str, request: Request, p: Principal = Depends(require("viewer"))):
        return await _decide(action_id, False, request, p)

    @app.post("/v1/assistant/triage/{alarm_id}")
    async def triage_alarm(alarm_id: str, request: Request, p: Principal = Depends(require("operator"))):
        ctx = ctx_for(request, p)
        alarms = await ctx.platform.alarms(state="open")
        alarm = next((a for a in alarms if a["alarm_id"] == alarm_id), None)
        if not alarm:
            raise HTTPException(404, "open alarm not found")
        return (await triage(llm, ctx, alarm)).model_dump()

    @app.post("/v1/assistant/workflows/draft")
    async def workflow_draft(body: DraftIn, p: Principal = Depends(require("integrator"))):
        try:
            return await draft_flow(llm, body.request)
        except FlowValidationError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/v1/assistant/knowledge", status_code=201)
    async def knowledge(body: KnowledgeIn, p: Principal = Depends(require("integrator"))):
        return {"chunks": await kb.ingest(p.tenant, body.doc, body.text, body.meta)}

    return app
