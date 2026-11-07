package nexiqon.authz_test

import rego.v1

import data.nexiqon.authz

actor(roles) := {"tenant_id": "t-a", "id": "u-1", "type": "user", "roles": roles, "groups": []}

test_admin_can_write_members if {
	authz.allow with input as {"actor": actor(["admin"]), "action": "identity.members.write", "resource": {"type": "membership"}}
}

test_member_can_read_but_not_write if {
	authz.allow with input as {"actor": actor(["member"]), "action": "identity.members.read", "resource": {"type": "membership"}}
	not authz.allow with input as {"actor": actor(["member"]), "action": "identity.members.write", "resource": {"type": "membership"}}
}

test_cross_tenant_always_denied if {
	not authz.allow with input as {"actor": actor(["owner"]), "action": "identity.members.read", "resource": {"type": "membership", "tenant_id": "t-b"}}
	d := authz.decision with input as {"actor": actor(["owner"]), "action": "identity.members.read", "resource": {"type": "membership", "tenant_id": "t-b"}}
	"cross-tenant resource" in d.reasons
}

test_owner_only_actions if {
	not authz.allow with input as {"actor": actor(["admin"]), "action": "identity.tenant.delete", "resource": {"type": "tenant"}}
	authz.allow with input as {"actor": actor(["owner"]), "action": "identity.tenant.delete", "resource": {"type": "tenant"}}
}

test_no_roles_denied if {
	not authz.allow with input as {"actor": actor([]), "action": "identity.members.read", "resource": {"type": "membership"}}
}

test_widget_cannot_escalate if {
	widget := {"tenant_id": "t-a", "id": "k-1", "type": "widget", "roles": ["admin"], "groups": []}
	not authz.allow with input as {"actor": widget, "action": "identity.members.write", "resource": {"type": "membership"}}
	authz.allow with input as {"actor": widget, "action": "agent.query.run", "resource": {"type": "agent"}}
}

test_editor_cannot_manage_members if {
	not authz.allow with input as {"actor": actor(["editor"]), "action": "identity.members.write", "resource": {"type": "membership"}}
	authz.allow with input as {"actor": actor(["editor"]), "action": "config.agent.write", "resource": {"type": "agent"}}
}

test_decision_lists_granting_role if {
	d := authz.decision with input as {"actor": actor(["editor"]), "action": "config.agent.write", "resource": {"type": "agent"}}
	d.allow
	"granted by role editor" in d.reasons
}

test_audit_log_is_admin_only if {
	not authz.allow with input as {"actor": actor(["member"]), "action": "audit.events.read", "resource": {"type": "audit_event"}}
	not authz.allow with input as {"actor": actor(["editor"]), "action": "audit.chain.verify", "resource": {"type": "audit_event"}}
	authz.allow with input as {"actor": actor(["admin"]), "action": "audit.events.read", "resource": {"type": "audit_event"}}
	d := authz.decision with input as {"actor": actor(["member"]), "action": "audit.events.read", "resource": {"type": "audit_event"}}
	"admin-only action" in d.reasons
}
