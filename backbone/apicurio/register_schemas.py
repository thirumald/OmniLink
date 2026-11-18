"""Register exported JSON Schemas in Apicurio Registry 3 with a BACKWARD rule.

    APICURIO_URL=http://localhost:8085 python backbone/apicurio/register_schemas.py contracts/schemas
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx

GROUP = "omnilink"


def register(base: str, schema_dir: Path) -> None:
    api = f"{base.rstrip('/')}/apis/registry/v3/groups/{GROUP}/artifacts"
    with httpx.Client(timeout=15) as c:
        for f in sorted(schema_dir.glob("*.json")):
            artifact_id = f.stem
            body = {
                "artifactId": artifact_id,
                "artifactType": "JSON",
                "firstVersion": {"content": {"content": f.read_text(), "contentType": "application/json"}},
            }
            r = c.post(api, params={"ifExists": "FIND_OR_CREATE_VERSION"}, json=body)
            if r.status_code >= 400:
                raise SystemExit(f"{artifact_id}: {r.status_code} {r.text}")
            c.post(f"{api}/{artifact_id}/rules", json={"ruleType": "COMPATIBILITY", "config": "BACKWARD"})
            print("registered", artifact_id)


if __name__ == "__main__":
    register(os.environ.get("APICURIO_URL", "http://localhost:8085"), Path(sys.argv[1] if len(sys.argv) > 1 else "contracts/schemas"))
