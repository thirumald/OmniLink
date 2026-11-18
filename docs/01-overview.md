# 01 — What OmniLink is

OmniLink is the integration layer of a smart city: the single place where every field device and external system connects, where their data becomes consistent and trustworthy, and from which applications, automations and people act on it.

## The problem

City command centres inherit dozens of vendor systems: VMS, building management, traffic controllers, environmental sensors, utilities, EV chargers, partner agency feeds. Each speaks its own protocol and data model. The result is point-to-point integrations, duplicated data, no common alarm picture, and automation that breaks whenever a vendor changes. Proprietary integration platforms solve part of this, but they add licence cost, lock-in and data-sovereignty concerns, which matter most for government clients.

## What OmniLink provides

1. **One way in.** A Connector SDK and protocol adapters for MQTT, BACnet, Modbus, OPC UA, ONVIF, SNMP/NTCIP, LoRaWAN and REST/webhooks. Edge gateways keep data safe when the network fails.
2. **One language.** Every reading, event, alarm and command is a versioned canonical message with NGSI-LD entity IDs and UCUM units.
3. **One backbone.** Kafka carries everything; Flink enriches and evaluates rules within a second; ClickHouse and PostgreSQL store time series and relational data.
4. **One way to act.** Alarms follow ISA-18.2; commands are audited, rate-limited and need four-eyes approval where safety matters.
5. **Automation without lock-in.** Node-RED (visual, n8n-style) for integrators and Temporal for durable, mission-critical workflows.
6. **One governed front door.** APISIX gateway, signed outbound webhooks, live feeds, standards-based APIs.
7. **An AI assistant on top.** Open-weight LLMs answer questions over live data, triage alarms, propose actions a human must approve, and draft automations. It acts only with the user's own permissions.
8. **One console.** An Angular operator console in English and Arabic.

## Who uses it

| Persona | Uses OmniLink to |
| --- | --- |
| Command-centre operator | See the live city picture, acknowledge alarms, point cameras, ask the assistant |
| Shift supervisor | Approve critical commands, shelve or clear alarms, review incidents |
| Integrator / system engineer | Onboard devices and connectors, build flows, manage webhooks and partner access |
| Partner agency / external system | Push data in through REST/webhooks; receive signed events out |
| Platform engineer | Operate, scale and monitor the platform |

## Principles

- **Open source only** (OSI licences), so the client owns the platform and the data, with no per-device licence.
- **Sovereign by default.** It runs on-premises or in an in-country cloud, including the AI models.
- **Security in every layer.** Tenant isolation, least privilege, an audit trail, and humans in control of the AI.
- **Built layer by layer.** Each layer has a spec, code and tests, and can be deployed and verified on its own.
