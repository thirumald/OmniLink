"""Post-import Keycloak setup: set confidential client secrets from deploy/compose/.env and check the realm.

Realm import does not substitute environment variables, so secrets are pushed through the admin API.
    python tools/keycloak_setup.py --url http://localhost:8080 --env deploy/compose/.env
"""

from __future__ import annotations

import argparse
from pathlib import Path

import httpx

CLIENT_SECRETS = {
    "omnilink-gateway": "OIDC_GATEWAY_SECRET",
    "omnilink-nodered": "NODERED_CLIENT_SECRET",
    "omnilink-temporal": "TEMPORAL_CLIENT_SECRET",
    "omnilink-assistant": "ASSISTANT_CLIENT_SECRET",
    "omnilink-onboarding": "ONBOARDING_CLIENT_SECRET",
}


def read_env(path: Path) -> dict[str, str]:
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"')
    return env


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8080")
    ap.add_argument("--env", type=Path, default=Path("deploy/compose/.env"))
    ap.add_argument("--realm", default="omnilink")
    a = ap.parse_args()
    env = read_env(a.env)
    with httpx.Client(base_url=a.url, timeout=20) as c:
        tok = c.post("/realms/master/protocol/openid-connect/token", data={
            "grant_type": "password", "client_id": "admin-cli", "username": "admin",
            "password": env["KEYCLOAK_ADMIN_PASSWORD"]})
        tok.raise_for_status()
        h = {"Authorization": f"Bearer {tok.json()['access_token']}"}
        for client_id, var in CLIENT_SECRETS.items():
            found = c.get(f"/admin/realms/{a.realm}/clients", params={"clientId": client_id}, headers=h).json()
            if not found:
                print(f"MISSING client {client_id}")
                continue
            rep = found[0] | {"secret": env[var]}
            r = c.put(f"/admin/realms/{a.realm}/clients/{rep['id']}", json=rep, headers=h)
            r.raise_for_status()
            # verify by requesting a token with the new secret
            t = c.post(f"/realms/{a.realm}/protocol/openid-connect/token", data={
                "grant_type": "client_credentials", "client_id": client_id, "client_secret": env[var]})
            status = "ok" if t.status_code == 200 else f"token check failed ({t.status_code})"
            if client_id == "omnilink-gateway":
                status = "secret set"  # gateway has no service account; it only validates tokens
            print(f"{client_id:22s} {status}")


if __name__ == "__main__":
    main()
