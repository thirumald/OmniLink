"""Shared service plumbing: auth (Keycloak JWT), tenant context, metrics, app factory."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

REQS = Counter("omnilink_http_requests_total", "HTTP requests", ["service", "method", "route", "status"])
LAT = Histogram("omnilink_http_request_seconds", "HTTP latency", ["service", "route"])

ROLES = ("viewer", "operator", "supervisor", "integrator", "platform-admin")
# role -> roles it implies
IMPLIES = {
    "platform-admin": set(ROLES),
    "supervisor": {"supervisor", "operator", "viewer"},
    "operator": {"operator", "viewer"},
    "integrator": {"integrator", "viewer"},
    "viewer": {"viewer"},
}


@dataclass
class Principal:
    sub: str
    tenant: str
    roles: set[str] = field(default_factory=set)
    username: str = ""

    def has(self, role: str) -> bool:
        return any(role in IMPLIES.get(r, set()) for r in self.roles)


@lru_cache(maxsize=1)
def _jwks_client():
    import jwt

    issuer = os.environ["OIDC_ISSUER"]  # e.g. https://sso.omnilink.local/realms/omnilink
    return jwt.PyJWKClient(f"{issuer}/protocol/openid-connect/certs", cache_keys=True, lifespan=600)


def decode_token(token: str) -> Principal:
    import jwt

    key = _jwks_client().get_signing_key_from_jwt(token).key
    claims = jwt.decode(token, key, algorithms=["RS256", "ES256"], audience=os.environ.get("OIDC_AUDIENCE", "omnilink-api"),
                        issuer=os.environ["OIDC_ISSUER"])
    roles = set(claims.get("realm_access", {}).get("roles", [])) & set(ROLES)
    tenant = claims.get("tenant")
    if not tenant:
        raise HTTPException(403, "token has no tenant claim")
    return Principal(sub=claims["sub"], tenant=tenant, roles=roles, username=claims.get("preferred_username", ""))


_bearer = HTTPBearer(auto_error=False)


async def current_principal(request: Request, cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> Principal:
    # Dev mode only: identity from headers. Never enable in production (APISIX strips these headers).
    if os.environ.get("OMNILINK_AUTH_MODE") == "dev":
        return Principal(sub=request.headers.get("x-user", "dev"), tenant=request.headers.get("x-tenant", "abudhabi"),
                         roles=set(request.headers.get("x-roles", "platform-admin").split(",")),
                         username=request.headers.get("x-user", "dev"))
    if cred is None:
        raise HTTPException(401, "missing bearer token")
    try:
        return decode_token(cred.credentials)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(401, f"invalid token: {exc}") from exc


def require(role: str):
    async def dep(p: Principal = Depends(current_principal)) -> Principal:
        if not p.has(role):
            raise HTTPException(403, f"requires role '{role}'")
        return p

    return dep


def create_app(service: str, title: str, lifespan=None) -> FastAPI:
    app = FastAPI(title=title, version="1.0.0", lifespan=lifespan)

    @app.middleware("http")
    async def metrics(request: Request, call_next):
        t0 = time.perf_counter()
        resp = await call_next(request)
        route = getattr(request.scope.get("route"), "path", "unmatched")
        REQS.labels(service, request.method, route, resp.status_code).inc()
        LAT.labels(service, route).observe(time.perf_counter() - t0)
        return resp

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return {"status": "ok", "service": service}

    @app.get("/metrics", include_in_schema=False)
    async def prom():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app
