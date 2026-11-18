# Layer 10 — AI Assistant (LLM on top of the platform)

**Purpose.** Give operators, supervisors and integrators a co-pilot that understands the city's live state, suggests what to do, and automates the routine work, without ever bypassing platform security or human control.

## 1. Capabilities

| Capability | Who uses it | How it works |
| --- | --- | --- |
| **Ask the city** (natural-language Q&A) | all roles | Agent calls read tools: devices, entities, time series, alarms, incidents, knowledge base |
| **Alarm triage suggestions** | operators | On every P1/P2 alarm: gathers context (alarm, entity, last 6 h of data, nearby devices, similar past incidents, runbook) → structured suggestion published to `omnilink.ai-suggestions.v1` and shown next to the alarm |
| **Action proposals** | operators, supervisors | Agent proposes write actions (ack alarm, PTZ preset, set-point change, webhook); each becomes a *pending action* the user approves or rejects in the console |
| **Workflow generation** | integrators | Plain-language request → validated Node-RED flow JSON using only OmniLink + core nodes → imported as a draft for review |
| **Reports and summaries** | supervisors | Shift handover summary, incident timeline, weekly KPI narrative |
| **Runbook / document RAG** | all | SOPs, device manuals, past incident reports chunked and embedded in pgvector |
| **MCP server** | other AI tools / IDEs | Same tool set exposed over the Model Context Protocol |

## 2. Architecture

```
Angular console ──► APISIX ──► assistant service (FastAPI)
                                   │  agent loop (tool calling, max 8 steps)
                                   ├─► LLM gateway (OpenAI-compatible): vLLM │ LiteLLM proxy │ Ollama (dev)
                                   ├─► embeddings: bge-m3 via vLLM / Text Embeddings Inference
                                   ├─► knowledge store: PostgreSQL + pgvector
                                   └─► platform APIs, called WITH THE USER'S TOKEN (RBAC + tenant enforced by services)
Kafka omnilink.alarms.v1 ──► triage worker ──► omnilink.ai-suggestions.v1 ──► Centrifugo ──► console
```

## 3. Open-source model stack

| Purpose | Default | Licence | Alternatives |
| --- | --- | --- | --- |
| Chat / tool calling | Qwen2.5-32B-Instruct or Qwen3-32B (AWQ on 1–2× L40S / A100) | Apache 2.0 | Mistral Small 3.x (Apache 2.0); Jais (Apache 2.0) for Arabic-first |
| Small / edge model | Qwen2.5-7B-Instruct | Apache 2.0 | Mistral 7B Instruct (Apache 2.0) |
| Embeddings | BAAI bge-m3 (multilingual, Arabic + English) | MIT | multilingual-e5-large (MIT) |
| Reranker | bge-reranker-v2-m3 | Apache 2.0 | – |
| Serving | vLLM | Apache 2.0 | Ollama (MIT) for dev, TGI |
| Gateway / budgets | LiteLLM proxy (core) | MIT | direct to vLLM |
| Tracing / evals | Langfuse (core) or OpenTelemetry → Tempo | MIT | – |

Models with non-OSI licences (e.g. Llama community licence) are excluded by the licence policy. The model is a configuration value (`OMNILINK_LLM_MODEL`), so a client can swap in a commercial endpoint if they choose.

## 4. Safety model

1. **No privilege of its own.** Tools call platform APIs with the requesting user's bearer token. The assistant can never do what the user could not do.
2. **Write tools never execute directly.** They create a pending action (`/v1/assistant/actions/{id}/approve`). Approval re-checks the user's role; critical commands still need a second supervisor in the command service.
3. **Role-scoped tool list.** A viewer's agent is not even offered write tools.
4. **Tool output is data, not instructions.** Tool results are wrapped and scanned; text that tries to issue instructions is neutralised.
5. **Generated workflows are drafts.** Validator allows only known node types and checks every wire; nothing is deployed without review.
6. **Full audit.** Every prompt, tool call, result size, proposal and approval is logged with user and tenant; traces go to Tempo/Langfuse.
7. **Data stays in-country.** Models run on-premises; no external API calls by default.

## 5. API

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/v1/assistant/chat` | `{session_id?, message}` → answer, tool trace, pending actions |
| POST | `/v1/assistant/actions/{id}/approve` / `reject` | Execute or discard a proposed action |
| POST | `/v1/assistant/triage/{alarm_id}` | On-demand triage suggestion |
| POST | `/v1/assistant/workflows/draft` | `{request}` → validated Node-RED flow JSON |
| POST | `/v1/assistant/knowledge` | Ingest a document (markdown/text) into the knowledge base |

## 6. Acceptance criteria

- [ ] Agent tests with a scripted LLM: read tools execute, write tools become pending actions, viewers never see write tools.
- [ ] Workflow validator rejects unknown node types, dangling wires and inline secrets.
- [ ] Triage output validates against the `TriageSuggestion` schema; invalid LLM output falls back to a rule-based summary.
- [ ] Red-team suite: prompt injection in device names / documents cannot trigger a write.
- [ ] p95 chat answer (3 tool calls) < 8 s on Qwen2.5-32B AWQ, 1× L40S.
