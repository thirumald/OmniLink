import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ["libs/omnilink_contracts", "libs/omnilink_sdk", "services", "connectors", "edge", "workflow/temporal", "assistant", "."]:
    sys.path.insert(0, str(ROOT / p))
