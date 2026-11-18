"""Render ${VAR} placeholders in a file from an .env file plus the environment (for Debezium JSON, Flink SQL).

    python tools/render_template.py storage/debezium/postgres-connector.json --env deploy/compose/.env
Fails if any placeholder is left unresolved.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from keycloak_setup import read_env

_VAR = re.compile(r"\$\{([A-Z0-9_]+)\}")


def render(text: str, values: dict[str, str]) -> str:
    missing = sorted({m for m in _VAR.findall(text) if m not in values})
    if missing:
        raise KeyError(", ".join(missing))
    return _VAR.sub(lambda m: values[m.group(1)], text)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", type=Path)
    ap.add_argument("--env", type=Path, default=Path("deploy/compose/.env"))
    ap.add_argument("--set", action="append", default=[], help="KEY=VALUE overrides")
    a = ap.parse_args()
    values = {**read_env(a.env), **os.environ, **dict(kv.split("=", 1) for kv in a.set)}
    try:
        sys.stdout.write(render(a.file.read_text(), values))
    except KeyError as exc:
        raise SystemExit(f"unresolved placeholders in {a.file}: {exc}") from exc


if __name__ == "__main__":
    main()
