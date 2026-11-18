# Layer 3 — Edge Gateway

**Purpose.** Run connectors close to field networks (BACnet MS/TP, Modbus RTU, serial, isolated OT VLANs) and keep data safe when the WAN to the core fails.

## 1. Components

| Component | Tech | Responsibility |
| --- | --- | --- |
| Edge runtime | K3s (single node or 3-node HA) | Runs connector pods, local broker, Node-RED |
| Local broker | NanoMQ (MIT) | Local MQTT for field devices and edge flows; bridges to core |
| Connectors | same images as core, `OMNILINK_UPLINK=mqtt` | Poll / subscribe to devices; publish canonical messages |
| Store-and-forward | `BufferedPublisher` + SQLite on a PVC | ≥ 72 h buffering, ordered replay |
| Edge flows | Node-RED (Apache 2.0) | Local interlocks that must work offline (e.g. pump trip, barrier control) |
| Uplink bridge (core side) | `edge/uplink_bridge.py` | MQTT `omnilink/v1/<topic>/<key>` → Kafka `<topic>` with the same key |

## 2. Data path

```
device → connector (edge) → BufferedPublisher ──MQTT 5 / TLS 1.3 / mTLS──► core broker (RabbitMQ MQTT)
                                     │ (WAN down)                                   │
                                     └── SQLite buffer, replay in order             ▼
                                                                    uplink-bridge → Kafka
```

- QoS 1 end to end; the bridge produces to Kafka **before** acknowledging the MQTT message (manual ack), so nothing is lost between broker and Kafka.
- Topic allow-list in the bridge: only canonical topics may be forwarded; anything else goes to the DLQ.
- Each gateway authenticates with its own X.509 certificate; the bridge checks that the tenant in the key matches the certificate's tenant.

## 3. Commands to the edge

The core command-service publishes to Kafka `omnilink.commands.v1`; the bridge mirrors commands for edge connectors to MQTT `omnilink/v1/cmd/<gateway_id>`, which the edge connector consumes (`OMNILINK_COMMAND_SOURCE=mqtt`).

## 4. Hardware baseline (per gateway)

| Site size | CPU | RAM | Disk | Ports |
| --- | --- | --- | --- | --- |
| Small (≤ 500 points) | 4 cores ARM64/x86 | 8 GB | 128 GB SSD | 2× Ethernet, RS-485 |
| Large (≤ 10,000 points) | 8 cores x86 | 32 GB | 512 GB SSD | 4× Ethernet, RS-485, LTE backup |

## 5. Acceptance criteria

- [ ] WAN cut for 1 h at 1,000 msg/s: zero loss, replay order preserved, backlog drained in < 15 min.
- [ ] Gateway reboot keeps its buffer (PVC on local SSD).
- [ ] Bridge rejects topics outside the allow-list and tenant mismatches (unit tests).
- [ ] Zero-touch provisioning: a new gateway joins with one bootstrap token and gets its config from GitOps.
