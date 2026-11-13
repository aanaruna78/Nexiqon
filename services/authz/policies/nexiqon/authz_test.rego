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

test_any_tenant_role_may_run_inference_but_not_manage if {
	authz.allow with input as {"actor": actor(["member"]), "action": "model.inference.run", "resource": {"type": "model_profile"}}
	widget := {"tenant_id": "t-a", "id": "k-1", "type": "widget", "roles": ["end_user"], "groups": []}
	authz.allow with input as {"actor": widget, "action": "model.inference.run", "resource": {"type": "model_profile"}}
	not authz.allow with input as {"actor": widget, "action": "config.model_profile.write", "resource": {"type": "model_profile"}}
}

test_inference_callers_may_resolve_profiles_without_reading_the_registry if {
	widget := {"tenant_id": "t-a", "id": "k-1", "type": "widget", "roles": ["end_user"], "groups": []}
	authz.allow with input as {"actor": widget, "action": "config.profiles.resolve", "resource": {"type": "model_profile"}}
	authz.allow with input as {"actor": actor(["end_user"]), "action": "config.profiles.resolve", "resource": {"type": "model_profile"}}
	not authz.allow with input as {"actor": widget, "action": "config.model_profile.read", "resource": {"type": "model_profile"}}
	not authz.allow with input as {"actor": actor(["end_user"]), "action": "config.model_profile.read", "resource": {"type": "model_profile"}}
}

test_ingestion_service_identity_is_narrow if {
	svc := {"tenant_id": "t-a", "id": "service:ingestion", "type": "service", "roles": ["service:ingestion"], "groups": []}
	authz.allow with input as {"actor": svc, "action": "retrieval.index.write", "resource": {"type": "document"}}
	authz.allow with input as {"actor": svc, "action": "model.inference.run", "resource": {"type": "model_profile"}}
	not authz.allow with input as {"actor": svc, "action": "identity.members.write", "resource": {"type": "member"}}
	not authz.allow with input as {"actor": svc, "action": "config.agent.write", "resource": {"type": "agent"}}
	not authz.allow with input as {"actor": svc, "action": "retrieval.index.write", "resource": {"type": "document", "tenant_id": "t-b"}}
}

test_index_writes_are_service_only if {
	not authz.allow with input as {"actor": actor(["editor"]), "action": "retrieval.index.write", "resource": {"type": "document"}}
	not authz.allow with input as {"actor": actor(["owner"]), "action": "retrieval.index.write", "resource": {"type": "document"}}
	authz.allow with input as {"actor": actor(["editor"]), "action": "retrieval.index.read", "resource": {"type": "document"}}
}

test_search_is_open_to_inference_callers if {
	widget := {"tenant_id": "t-a", "id": "k-1", "type": "widget", "roles": ["end_user"], "groups": []}
	authz.allow with input as {"actor": widget, "action": "retrieval.search.run", "resource": {"type": "collection"}}
	authz.allow with input as {"actor": widget, "action": "retrieval.search.verify", "resource": {"type": "collection"}}
	authz.allow with input as {"actor": widget, "action": "retrieval.search.answer", "resource": {"type": "collection"}}
	authz.allow with input as {"actor": actor(["member"]), "action": "retrieval.search.run", "resource": {"type": "collection"}}
	not authz.allow with input as {"actor": widget, "action": "retrieval.index.read", "resource": {"type": "document"}}
	not authz.allow with input as {"actor": actor(["member"]), "action": "retrieval.search.run", "resource": {"type": "collection", "tenant_id": "t-b"}}
}

test_agent_runtime_identity_reads_config_only if {
	svc := {"tenant_id": "t-a", "id": "service:agent-runtime", "type": "service", "roles": ["service:agent-runtime"], "groups": []}
	authz.allow with input as {"actor": svc, "action": "config.agent.read", "resource": {"type": "agent"}}
	authz.allow with input as {"actor": svc, "action": "ingestion.collections.read", "resource": {"type": "collection"}}
	not authz.allow with input as {"actor": svc, "action": "retrieval.search.run", "resource": {"type": "collection"}}
	not authz.allow with input as {"actor": svc, "action": "model.inference.run", "resource": {"type": "model_profile"}}
	not authz.allow with input as {"actor": svc, "action": "ingestion.documents.read", "resource": {"type": "document"}}
}

test_end_users_read_only_their_own_conversations if {
	authz.allow with input as {"actor": actor(["end_user"]), "action": "conversation.own.read", "resource": {"type": "conversation"}}
	not authz.allow with input as {"actor": actor(["end_user"]), "action": "conversation.all.read", "resource": {"type": "conversation"}}
	authz.allow with input as {"actor": actor(["member"]), "action": "conversation.all.read", "resource": {"type": "conversation"}}
}

test_tool_invocation_by_risk if {
	widget := {"tenant_id": "t-a", "id": "k-1", "type": "widget", "roles": ["end_user"], "groups": []}
	authz.allow with input as {"actor": widget, "action": "tool.invoke.read", "resource": {"type": "tool"}}
	authz.allow with input as {"actor": widget, "action": "tool.invoke.write", "resource": {"type": "tool"}}
	not authz.allow with input as {"actor": widget, "action": "tool.invoke.high", "resource": {"type": "tool"}}
	not authz.allow with input as {"actor": actor(["editor"]), "action": "tool.invoke.high", "resource": {"type": "tool"}}
	authz.allow with input as {"actor": actor(["admin"]), "action": "tool.invoke.high", "resource": {"type": "tool"}}
	not authz.allow with input as {"actor": actor(["member"]), "action": "tool.credentials.write", "resource": {"type": "credential"}}
	not authz.allow with input as {"actor": actor(["editor"]), "action": "tool.credentials.read", "resource": {"type": "credential"}}
	not authz.allow with input as {"actor": widget, "action": "tool.approvals.decide", "resource": {"type": "approval"}}
}

test_tool_gateway_identity_reads_config_only if {
	svc := {"tenant_id": "t-a", "id": "service:tool-gateway", "type": "service", "roles": ["service:tool-gateway"], "groups": []}
	authz.allow with input as {"actor": svc, "action": "config.tool.read", "resource": {"type": "tool"}}
	not authz.allow with input as {"actor": svc, "action": "tool.invoke.read", "resource": {"type": "tool"}}
	not authz.allow with input as {"actor": svc, "action": "config.tool.write", "resource": {"type": "tool"}}
}
