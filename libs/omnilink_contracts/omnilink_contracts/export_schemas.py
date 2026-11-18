"""Export JSON Schemas for every canonical model, and optionally check for drift.

    python -m omnilink_contracts.export_schemas --out contracts/schemas          # write
    python -m omnilink_contracts.export_schemas --out contracts/schemas --check  # CI drift check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .models import MODELS, SCHEMA_VERSION


def render() -> dict[str, str]:
    out = {}
    for name, model in MODELS.items():
        schema = model.model_json_schema()
        schema["$id"] = f"https://schemas.omnilink.local/v{SCHEMA_VERSION.split('.')[0]}/{name}.json"
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        out[f"{name}.json"] = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    drift = []
    for fname, text in render().items():
        path = args.out / fname
        if args.check:
            if not path.exists() or path.read_text() != text:
                drift.append(fname)
        else:
            path.write_text(text)
    if drift:
        print("schema drift:", ", ".join(drift), file=sys.stderr)
        return 1
    print(f"{'checked' if args.check else 'wrote'} {len(MODELS)} schemas in {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
