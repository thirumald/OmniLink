"""Air-quality station simulator (MQTT). Publishes city/aq/<id> every N seconds.

    python tools/simulators/mqtt_aq_sim.py --host localhost --stations 001,002 --spike-after 120
--spike-after makes PM2.5 jump above 55 µg/m³ after N seconds, to exercise rules, alarms and workflows.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import time
from datetime import UTC, datetime


def reading(station: str, t: float, spike: bool) -> dict:
    base = 30 + 8 * math.sin(t / 300) + random.uniform(-2, 2)
    return {"station": station, "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "pm25": round(base + (40 if spike else 0), 1), "no2": round(20 + 5 * math.cos(t / 400) + random.uniform(-1, 1), 1)}


def main() -> None:
    import paho.mqtt.client as mqtt

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("MQTT_HOST", "localhost"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("MQTT_PORT", "1883")))
    ap.add_argument("--stations", default="001")
    ap.add_argument("--interval", type=float, default=5)
    ap.add_argument("--spike-after", type=float, default=float(os.environ.get("SPIKE_AFTER", "0")))
    a = ap.parse_args()
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"aq-sim-{os.getpid()}")
    if os.environ.get("MQTT_USER"):
        c.username_pw_set(os.environ["MQTT_USER"], os.environ.get("MQTT_PASSWORD"))
    c.connect(a.host, a.port)
    c.loop_start()
    t0 = time.time()
    while True:
        t = time.time() - t0
        for s in a.stations.split(","):
            msg = reading(s, t, a.spike_after > 0 and t > a.spike_after)
            c.publish(f"city/aq/{s}", json.dumps(msg), qos=1)
            print(json.dumps(msg), flush=True)
        time.sleep(a.interval)


if __name__ == "__main__":
    main()
