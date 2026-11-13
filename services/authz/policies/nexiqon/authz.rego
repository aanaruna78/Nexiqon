# Nexiqon authorization policy (ADR 0008).
#
# input = {
#   "actor":    {"tenant_id", "id", "type": user|service|api_key|widget, "roles": [..], "groups": [..]},
#   "action":   "<service>.<resource>.<verb>",          e.g. "identity.members.write"
#   "resource": {"type", "id"?, "tenant_id"?, "attributes"?}
# }
# Deny by default. Same tenant is always required. Permissions are globs with "." as delimiter:
# "*" matches one segment, "**" any number.
package nexiqon.authz

import rego.v1

# Role -> permission globs. Owner-only actions are excluded from admin by `owner_only`.
role_permissions := {
	"owner": ["**"],
	"admin": ["**"],
	"editor": [
		"**.read",
		"config.**",
		"knowledge.**",
		"ingestion.**",
		"retrieval.**",
		"agent.**",
		"conversation.**",
		"evaluation.**",
		"tool.definitions.read",
		"tool.definitions.test",
		"tool.invoke.*",
		"tool.openapi.import",
		"tool.approvals.decide",
		"model.inference.run",
	],
	"member": [
		"**.read",
		"conversation.**",
		"agent.query.run",
		"model.inference.run",
		"config.profiles.resolve",
		"retrieval.search.*",
		"tool.invoke.read",
		"tool.invoke.write",
	],
	"end_user": [
		"agent.query.run",
		"conversation.messages.create",
		"conversation.own.read",
		"model.inference.run",
		"config.profiles.resolve",
		"retrieval.search.*",
		"tool.definitions.read",
		"tool.invoke.read",
		"tool.invoke.write",
	],
	"service": ["**"],
	# Per-service identities (ADR 0017): tokens signed with a service's own key carry only this role.
	"service:ingestion": [
		"config.profiles.resolve",
		"model.inference.run",
		"retrieval.index.write",
		"retrieval.index.read",
	],
	# Reads agent configuration and collection names; model, retrieval and tool calls use the user's token.
	"service:agent-runtime": [
		"config.agent.read",
		"ingestion.collections.read",
	],
	# Reads tool definitions and agents' tool allowlists; invocations run as the calling user.
	"service:tool-gateway": [
		"config.tool.read",
		"config.agent.read",
	],
}

# Actions only an owner may perform, whatever other roles grant.
owner_only := {
	"identity.tenant.delete",
	"identity.owners.write",
	"governance.tenant.delete",
	"governance.tenant.export",
	"config.security_floors.write",
}

# Sensitive reads that "**.read" must not grant: only owners, admins and services.
admin_only := {
	"audit.events.read",
	"audit.chain.verify",
	"tool.invoke.high",
	"tool.credentials.read",
}

admin_roles := {"owner", "admin", "service"}

# Actions only service actors may perform (internal index writes), whatever a role says.
service_only := {"retrieval.index.write"}

# Actor types that may never hold administrative permissions, even if a role says so.
restricted_actor_types := {"widget"}

# The only actions a widget may perform.
widget_actions := {
	"agent.query.run",
	"conversation.messages.create",
	"conversation.own.read",
	"model.inference.run",
	"config.profiles.resolve",
	"retrieval.search.run",
	"retrieval.search.verify",
	"retrieval.search.answer",
	"tool.definitions.read",
	"tool.invoke.read",
	"tool.invoke.write",
}

resource_tenant := object.get(input.resource, "tenant_id", input.actor.tenant_id)

same_tenant if resource_tenant == input.actor.tenant_id

granting_roles contains role if {
	some role in input.actor.roles
	some pattern in role_permissions[role]
	glob.match(pattern, ["."], input.action)
}

owner_check_ok if not input.action in owner_only

owner_check_ok if {
	input.action in owner_only
	"owner" in input.actor.roles
}

admin_check_ok if not input.action in admin_only

admin_check_ok if {
	input.action in admin_only
	some role in input.actor.roles
	role in admin_roles
}

actor_type_ok if {
	not input.actor.type in restricted_actor_types
	service_check_ok
}

service_check_ok if not input.action in service_only

service_check_ok if {
	input.action in service_only
	input.actor.type == "service"
}

actor_type_ok if {
	input.actor.type in restricted_actor_types
	input.action in widget_actions
}

default allow := false

allow if {
	same_tenant
	count(granting_roles) > 0
	owner_check_ok
	admin_check_ok
	actor_type_ok
}

reasons contains "cross-tenant resource" if not same_tenant

reasons contains "no role grants this action" if count(granting_roles) == 0

reasons contains "owner-only action" if not owner_check_ok

reasons contains "actor type not permitted" if not actor_type_ok

reasons contains "admin-only action" if not admin_check_ok

reasons contains sprintf("granted by role %s", [role]) if {
	allow
	some role in granting_roles
}

decision := {"allow": allow, "reasons": sort(reasons)}
