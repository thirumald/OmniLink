# 03 — How OmniLink is developed

## 1. Method: layer by layer, spec → code → tests

Each layer is built in the same three steps, in dependency order:

1. **Spec**: `docs/layers/NN-*.md` defines purpose, components, interfaces (topics, APIs), data model and acceptance criteria.
2. **Code**: lives in the folder the spec names, written against the contracts of the layers below it.
3. **Tests**: unit and contract tests prove the acceptance criteria that can be checked without infrastructure. Integration and load tests run in the pilot environment at each phase gate.

| Build order | Layer | Depends on |
| --- | --- | --- |
| 1 | Contracts and event backbone | – |
| 2 | Connectivity (SDK and adapters) | 1 |
| 3 | Edge gateway | 1, 2 |
| 4 | Storage | 1 |
| 5 | Stream processing | 1, 4 |
| 6 | Platform services | 1, 4 |
| 7 | Workflow automation | 6 |
| 8 | API and integration | 6 |
| 9 | Security and observability | all (cross-cutting) |
| 10 | AI assistant | 6, 8 |
| 11 | Front end | 6, 8, 10 |

## 2. Conventions

- **Contracts first.** A change to a message starts in `libs/omnilink_contracts`. Run `make contracts` to regenerate JSON Schemas; CI fails on drift. Breaking changes create a new topic version (`.v2`).
- **No topic strings in code.** Use `omnilink_contracts.topics.T`.
- **Each service has a repository interface** with an in-memory implementation (tests, devstack) and a PostgreSQL implementation.
- **Every service exposes `/healthz` and `/metrics`** through `omnilink_services.common.create_app`.
- **Authorisation in the service, not only the UI.** Use `Depends(require("<role>"))`; check the tenant on every object.
- **Secrets only from environment / OpenBao.** Never in YAML, flows or code.
- **Python 3.12+, Pydantic v2, FastAPI, asyncio.** Format and lint with `ruff`.
- **Angular:** standalone components, signals, lazy routes, `inject()`, typed API client in `core/`.

## 3. Running and testing

```bash
make test             # all Python tests
make test-node        # Node-RED node tests
make test-console     # Angular unit tests (Vitest)
make contracts        # regenerate JSON Schemas
make devstack         # all services in one process with demo data on :9080
make console-build    # production build of the console (served by devstack)
```

`tools/devstack.py` runs the real service code with in-memory stores, a synthetic time series source and an offline demo LLM. Set `OMNILINK_LLM_URL` to use a real vLLM/Ollama endpoint.

## 4. Adding a protocol adapter

1. Create `connectors/adapters/<name>_adapter.py` with a class that extends `omnilink_sdk.Connector` and is decorated `@register("<name>")`.
2. Implement `connect`, then `read` (polling) and/or `subscribe` (push), and `execute` for commands.
3. Keep protocol parsing in pure functions (see `modbus_adapter.decode/encode`) and unit-test them.
4. Add the module to `ADAPTER_MODULES` in `omnilink_sdk/runner.py`, an example config in `connectors/examples/`, and a row in the Layer 2 spec.
5. Import third-party protocol libraries inside `connect()`, so tests and other adapters do not need them.

## 5. Adding a Node-RED node or assistant tool

- **Node-RED:** add a client method in `workflow/node-red/node-red-contrib-omnilink/lib/client.js`, register the node in `omnilink.js` with `makeNode`, add the editor template in `omnilink.html`, and add a test in `test/`. Add the type to `ALLOWED_NODE_TYPES` in the assistant's workflow generator.
- **Assistant tool:** add a `Tool` in `assistant/omnilink_assistant/tools.py`. Read tools run immediately; set `write=True` for anything that changes state (it becomes a proposal). Set `min_role`. Tools call platform APIs only through `PlatformClient`, which carries the user's token.

## 6. Branching, CI and releases

- Trunk-based: short-lived branches → pull request → review → merge to `main`.
- CI (`.github/workflows/ci.yml`): ruff, pytest, schema drift check, OPA tests, Node-RED node tests, Angular build and tests, `docker compose config`, Trivy scan.
- Releases are tagged `vMAJOR.MINOR.PATCH`; images are signed with Cosign; Kubernetes deployments are promoted by Argo CD (dev → test → prod).

## 7. Definition of done (per layer)

- [ ] Spec updated and acceptance criteria listed
- [ ] Code and tests merged; CI green
- [ ] Metrics, health and logs in place
- [ ] Security review: authz checks, tenant isolation, secrets
- [ ] Docs: README section, example configuration
