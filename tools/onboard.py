"""Onboard a site (connectors, devices, points, alarm rules) from one YAML file, through the APISIX gateway.

    python tools/onboard.py sites/pilot-simulators.yaml --api http://localhost:9080 --out connectors/generated
    python tools/onboard.py sites/my-site.yaml --dry-run           # validate only

Auth: OIDC client credentials from OIDC_TOKEN_URL / OIDC_CLIENT_ID / OIDC_CLIENT_SECRET (client omnilink-onboarding,
role integrator). For each connector, writes the connector config rendered by the asset registry to --out, ready for
`python -m omnilink_sdk.runner --config <file>`.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx
import yaml
from pydantic import BaseModel, Field, model_validator

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "libs/omnilink_contracts"), str(ROOT / "libs/omnilink_sdk"), str(ROOT / "services")]

from omnilink_sdk.normaliser import _CONVERSIONS  # noqa: E402
from omnilink_services.asset_registry import AlarmRuleIn, ConnectorIn, DeviceIn, PointIn  # noqa: E402

PROTOCOLS = {"mqtt", "modbus", "bacnet", "opcua", "onvif", "snmp", "http"}


class PointSpec(BaseModel):
    point_ref: str
    attribute: str
    unit: str | None = None
    source_unit: str | None = None
    scale: float = 1.0
    offset: float = 0.0
    deadband: float = 0.0
    writable: bool = False


class DeviceSpec(DeviceIn):
    connector: str
    points: list[PointSpec] = Field(default_factory=list)


class Site(BaseModel):
    tenant: str
    connectors: list[ConnectorIn]
    devices: list[DeviceSpec]
    rules: list[AlarmRuleIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self):
        ids = {c.id for c in self.connectors}
        errors = []
        for c in self.connectors:
            if c.type not in PROTOCOLS:
                errors.append(f"connector {c.id}: unknown type {c.type}")
        seen = set()
        for d in self.devices:
            if d.connector not in ids:
                errors.append(f"device {d.id}: unknown connector {d.connector}")
            for p in d.points:
                key = (d.connector, p.point_ref)
                if key in seen:
                    errors.append(f"device {d.id}: duplicate point_ref {p.point_ref} on {d.connector}")
                seen.add(key)
                if p.source_unit and p.unit and p.source_unit != p.unit and (p.source_unit, p.unit) not in _CONVERSIONS:
                    errors.append(f"device {d.id}/{p.attribute}: no unit conversion {p.source_unit} -> {p.unit}")
        types = {d.entity_type for d in self.devices}
        for r in self.rules:
            if r.entity_type and r.entity_type not in types:
                errors.append(f"rule {r.id}: no device of type {r.entity_type} in this site")
        if errors:
            raise ValueError("; ".join(errors))
        return self


def load_site(path: str | Path) -> Site:
    # ${VAR} references are kept as-is: the registry stores references, connectors expand them at runtime,
    # so secrets never reach the database or generated files.
    return Site.model_validate(yaml.safe_load(Path(path).read_text()))


def token() -> str | None:
    url = os.environ.get("OIDC_TOKEN_URL")
    if not url:
        return None
    r = httpx.post(url, data={"grant_type": "client_credentials", "client_id": os.environ.get("OIDC_CLIENT_ID", "omnilink-onboarding"),
                              "client_secret": os.environ["OIDC_CLIENT_SECRET"]}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def onboard(site: Site, api: str, out: Path, client: httpx.Client | None = None) -> list[Path]:
    tok = token()
    headers = {"Authorization": f"Bearer {tok}"} if tok else {"x-user": "onboard", "x-tenant": site.tenant, "x-roles": "integrator"}
    c = client or httpx.Client(base_url=api, headers=headers, timeout=30)

    def ok(r: httpx.Response):
        if r.status_code >= 400:
            raise SystemExit(f"{r.request.method} {r.request.url.path} -> {r.status_code}: {r.text[:300]}")

    for conn in site.connectors:
        ok(c.put(f"/v1/connectors/{conn.id}", json=conn.model_dump()))
        print(f"connector  {conn.id} ({conn.type})")
    for d in site.devices:
        body = d.model_dump(exclude={"points", "connector"}) | {"connector_id": d.connector}
        ok(c.put(f"/v1/devices/{d.id}", json=body))
        print(f"device     {d.id} ({d.entity_type}) {len(d.points)} points")
    for conn in site.connectors:
        pts = [PointIn(device_id=d.id, **p.model_dump()).model_dump() for d in site.devices if d.connector == conn.id
               for p in d.points]
        if pts:
            ok(c.post(f"/v1/connectors/{conn.id}/points", json=pts))
    for r in site.rules:
        ok(c.put(f"/v1/rules/{r.id}", json=r.model_dump()))
        print(f"rule       {r.id}: {r.attribute} {r.condition} {r.threshold} -> P{r.priority}")
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for conn in site.connectors:
        r = c.get(f"/v1/connectors/{conn.id}/config")
        ok(r)
        path = out / f"{conn.id}.yaml"
        path.write_text(yaml.safe_dump(r.json(), sort_keys=False))
        written.append(path)
        print(f"config  -> {path}")
    return written


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("site")
    ap.add_argument("--api", default=os.environ.get("OMNILINK_API", "http://localhost:9080"))
    ap.add_argument("--out", type=Path, default=ROOT / "connectors/generated")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    try:
        site = load_site(a.site)
    except ValueError as exc:
        raise SystemExit(f"invalid site file: {exc}") from exc
    print(f"site OK: {len(site.connectors)} connectors, {len(site.devices)} devices, "
          f"{sum(len(d.points) for d in site.devices)} points, {len(site.rules)} rules")
    if not a.dry_run:
        onboard(site, a.api, a.out)


if __name__ == "__main__":
    main()
