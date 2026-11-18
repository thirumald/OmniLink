# OmniLink documentation

| Document | Read it to learn |
| --- | --- |
| [01 — Overview](01-overview.md) | What OmniLink is, the problem it solves, who uses it |
| [02 — Architecture](02-architecture.md) | The 11 layers, data and command flows, design principles |
| [03 — Development guide](03-development-guide.md) | How the platform is built: method, repo conventions, testing, adding connectors and nodes |
| [04 — Tech stack and licences](04-tech-stack-and-licences.md) | Every component, its licence, and its licensed commercial alternative |
| [05 — Deployment](05-deployment.md) | Dev stack, Docker Compose pilot, Kubernetes production, sizing |
| [06 — Roadmap and status](06-roadmap.md) | What is built and tested, what is next, release gates |
| [07 — Bring-up runbook](07-bring-up-runbook.md) | Start the stack layer by layer with verification, prove it with simulators, connect the first real devices |

## Layer specifications

Each layer has its own spec covering purpose, components, interfaces, configuration and acceptance criteria. The code for each layer lives in the folder named in its spec.

| # | Layer | Spec |
| --- | --- | --- |
| 1 | Contracts and event backbone | [layers/01-contracts-backbone.md](layers/01-contracts-backbone.md) |
| 2 | Connectivity (Connector SDK and adapters) | [layers/02-connectivity.md](layers/02-connectivity.md) |
| 3 | Edge gateway | [layers/03-edge-gateway.md](layers/03-edge-gateway.md) |
| 4 | Data storage | [layers/04-storage.md](layers/04-storage.md) |
| 5 | Stream processing | [layers/05-stream-processing.md](layers/05-stream-processing.md) |
| 6 | Platform services | [layers/06-platform-services.md](layers/06-platform-services.md) |
| 7 | Workflow automation | [layers/07-workflow-automation.md](layers/07-workflow-automation.md) |
| 8 | API and external integration | [layers/08-api-integration.md](layers/08-api-integration.md) |
| 9 | Security and observability | [layers/09-security-observability.md](layers/09-security-observability.md) |
| 10 | AI assistant | [layers/10-ai-assistant.md](layers/10-ai-assistant.md) |
| 11 | Front end (Angular console) | [layers/11-frontend-console.md](layers/11-frontend-console.md) |

The event contracts are also described as AsyncAPI in [api/asyncapi.yaml](api/asyncapi.yaml). OpenAPI specs come from each service at `/openapi.json`.
