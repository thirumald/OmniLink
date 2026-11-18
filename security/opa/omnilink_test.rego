package omnilink.commands_test

import data.omnilink.commands
import rego.v1

test_operator_can_move_camera if {
	commands.allow with input as {"user": {"roles": ["operator"], "tenant": "abudhabi"},
		"command": {"action": "ptz.goto_preset", "entity_type": "Camera", "tenant": "abudhabi"}}
}

test_operator_cannot_open_flood_gate if {
	not commands.allow with input as {"user": {"roles": ["operator"], "tenant": "abudhabi"},
		"command": {"action": "write_point", "entity_type": "FloodGate", "tenant": "abudhabi"}}
}

test_cross_tenant_denied if {
	not commands.allow with input as {"user": {"roles": ["supervisor"], "tenant": "rak"},
		"command": {"action": "write_point", "entity_type": "Camera", "tenant": "abudhabi"}}
}

test_reboot_needs_approval if {
	commands.requires_approval with input as {"command": {"action": "reboot", "entity_type": "Camera"}}
}
