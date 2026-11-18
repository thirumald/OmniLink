package omnilink.commands

import rego.v1

# input: {"user": {"roles": [...], "tenant": "..."}, "command": {"action": "...", "entity_type": "...", "tenant": "..."}}

default allow := false

# entity types whose commands are life-safety relevant
critical_types := {"FloodGate", "FireDamper", "TrafficSignalController", "Barrier", "WaterPump"}

read_only_actions := {"snapshot"}

allow if {
	input.user.tenant == input.command.tenant
	input.command.action in read_only_actions
	"viewer" in input.user.roles
}

allow if {
	input.user.tenant == input.command.tenant
	not input.command.entity_type in critical_types
	some r in input.user.roles
	r in {"operator", "supervisor"}
}

allow if {
	input.user.tenant == input.command.tenant
	input.command.entity_type in critical_types
	"supervisor" in input.user.roles
}

allow if "platform-admin" in input.user.roles

requires_approval if input.command.entity_type in critical_types

requires_approval if input.command.action in {"reboot", "relinquish", "firmware.update"}
