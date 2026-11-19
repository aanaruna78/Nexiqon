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

test_widget_reads_channel_settings_and_channel_service_reads_agents_only if {
	widget := {"tenant_id": "t-a", "id": "k-1", "type": "widget", "roles": ["end_user"], "groups": []}
	authz.allow with input as {"actor": widget, "action": "channel.settings.read", "resource": {"type": "agent"}}
	svc := {"tenant_id": "t-a", "id": "service:channel", "type": "service", "roles": ["service:channel"], "groups": []}
	authz.allow with input as {"actor": svc, "action": "config.agent.read", "resource": {"type": "agent"}}
	not authz.allow with input as {"actor": svc, "action": "config.tool.read", "resource": {"type": "tool"}}
	not authz.allow with input as {"actor": svc, "action": "agent.query.run", "resource": {"type": "agent"}}
}

test_only_builders_run_unreleased_assistant_versions if {
	authz.allow with input as {"actor": actor(["editor"]), "action": "agent.versions.preview", "resource": {"type": "agent"}}
	not authz.allow with input as {"actor": actor(["member"]), "action": "agent.versions.preview", "resource": {"type": "agent"}}
	not authz.allow with input as {"actor": actor(["end_user"]), "action": "agent.versions.preview", "resource": {"type": "agent"}}
}

test_evaluation_identity_asks_assistants_but_never_invokes_tools if {
	svc := {"tenant_id": "t-a", "id": "service:evaluation", "type": "service", "roles": ["service:evaluation"], "groups": []}
	authz.allow with input as {"actor": svc, "action": "agent.query.run", "resource": {"type": "agent"}}
	authz.allow with input as {"actor": svc, "action": "agent.versions.preview", "resource": {"type": "agent"}}
	authz.allow with input as {"actor": svc, "action": "retrieval.search.run", "resource": {"type": "collection"}}
	not authz.allow with input as {"actor": svc, "action": "tool.invoke.read", "resource": {"type": "tool"}}
	not authz.allow with input as {"actor": svc, "action": "tool.invoke.write", "resource": {"type": "tool"}}
	not authz.allow with input as {"actor": svc, "action": "config.agent.write", "resource": {"type": "agent"}}
	not authz.allow with input as {"actor": svc, "action": "agent.query.run", "resource": {"type": "agent", "tenant_id": "t-b"}}
}

test_evaluation_answers_and_release_overrides if {
	authz.allow with input as {"actor": actor(["editor"]), "action": "evaluation.results.view", "resource": {"type": "evaluation_run"}}
	not authz.allow with input as {"actor": actor(["member"]), "action": "evaluation.results.view", "resource": {"type": "evaluation_run"}}
	not authz.allow with input as {"actor": actor(["member"]), "action": "evaluation.cases.view", "resource": {"type": "test_set"}}
	authz.allow with input as {"actor": actor(["member"]), "action": "evaluation.runs.read", "resource": {"type": "agent"}}
	not authz.allow with input as {"actor": actor(["editor"]), "action": "config.release.override", "resource": {"type": "agent"}}
	authz.allow with input as {"actor": actor(["admin"]), "action": "config.release.override", "resource": {"type": "agent"}}
}

test_only_services_send_email if {
	svc := {"tenant_id": "t-a", "id": "service:conversation", "type": "service", "roles": ["service:conversation"], "groups": []}
	authz.allow with input as {"actor": svc, "action": "notification.email.send", "resource": {"type": "email"}}
	not authz.allow with input as {"actor": svc, "action": "conversation.all.read", "resource": {"type": "conversation"}}
	not authz.allow with input as {"actor": actor(["owner"]), "action": "notification.email.send", "resource": {"type": "email"}}
	widget := {"tenant_id": "t-a", "id": "k-1", "type": "widget", "roles": ["end_user"], "groups": []}
	not authz.allow with input as {"actor": widget, "action": "notification.email.send", "resource": {"type": "email"}}
	authz.allow with input as {"actor": widget, "action": "conversation.messages.create", "resource": {"type": "conversation"}}
}

test_metering_and_the_escalation_queue if {
	svc := {"tenant_id": "t-a", "id": "service:metering", "type": "service", "roles": ["service:metering"], "groups": []}
	authz.allow with input as {"actor": svc, "action": "conversation.insights.read", "resource": {"type": "conversation"}}
	not authz.allow with input as {"actor": svc, "action": "conversation.all.read", "resource": {"type": "conversation"}}
	authz.allow with input as {"actor": actor(["member"]), "action": "metering.usage.read", "resource": {"type": "usage"}}
	not authz.allow with input as {"actor": actor(["member"]), "action": "metering.gaps.view", "resource": {"type": "insights"}}
	authz.allow with input as {"actor": actor(["editor"]), "action": "metering.gaps.view", "resource": {"type": "insights"}}
	not authz.allow with input as {"actor": actor(["editor"]), "action": "metering.budgets.write", "resource": {"type": "budget"}}
	authz.allow with input as {"actor": actor(["admin"]), "action": "metering.budgets.write", "resource": {"type": "budget"}}
	authz.allow with input as {"actor": actor(["member"]), "action": "conversation.queue.write", "resource": {"type": "conversation"}}
	widget := {"tenant_id": "t-a", "id": "k-1", "type": "widget", "roles": ["end_user"], "groups": []}
	not authz.allow with input as {"actor": widget, "action": "conversation.queue.write", "resource": {"type": "conversation"}}
}

test_only_governance_runs_lifecycles_and_only_owners_delete_or_export if {
	svc := {"tenant_id": "t-a", "id": "service:governance", "type": "service", "roles": ["service:governance"], "groups": []}
	authz.allow with input as {"actor": svc, "action": "governance.lifecycle.run", "resource": {"type": "tenant"}}
	not authz.allow with input as {"actor": svc, "action": "governance.lifecycle.run", "resource": {"type": "tenant", "tenant_id": "t-b"}}
	not authz.allow with input as {"actor": actor(["owner"]), "action": "governance.lifecycle.run", "resource": {"type": "tenant"}}
	authz.allow with input as {"actor": actor(["owner"]), "action": "governance.tenant.delete", "resource": {"type": "tenant"}}
	not authz.allow with input as {"actor": actor(["admin"]), "action": "governance.tenant.delete", "resource": {"type": "tenant"}}
	not authz.allow with input as {"actor": actor(["admin"]), "action": "governance.tenant.export", "resource": {"type": "tenant"}}
	authz.allow with input as {"actor": actor(["admin"]), "action": "governance.retention.run", "resource": {"type": "tenant"}}
	not authz.allow with input as {"actor": actor(["editor"]), "action": "governance.retention.run", "resource": {"type": "tenant"}}
	authz.allow with input as {"actor": actor(["member"]), "action": "governance.requests.read", "resource": {"type": "tenant"}}
}

test_webhooks_are_for_admins_and_the_inbox_for_everyone_in_studio if {
	not authz.allow with input as {"actor": actor(["editor"]), "action": "notification.webhooks.read", "resource": {"type": "webhook"}}
	not authz.allow with input as {"actor": actor(["editor"]), "action": "notification.webhooks.write", "resource": {"type": "webhook"}}
	authz.allow with input as {"actor": actor(["admin"]), "action": "notification.webhooks.write", "resource": {"type": "webhook"}}
	authz.allow with input as {"actor": actor(["member"]), "action": "notification.inbox.read", "resource": {"type": "inbox"}}
	widget := {"tenant_id": "t-a", "id": "k-1", "type": "widget", "roles": ["end_user"], "groups": []}
	not authz.allow with input as {"actor": widget, "action": "notification.inbox.read", "resource": {"type": "inbox"}}
}

test_the_config_mirror_only_pulls_snapshots if {
	svc := {"tenant_id": "t-a", "id": "service:config-mirror", "type": "service", "roles": ["service:config-mirror"], "groups": []}
	authz.allow with input as {"actor": svc, "action": "config.snapshots.read", "resource": {"type": "snapshot"}}
	not authz.allow with input as {"actor": svc, "action": "config.snapshots.read", "resource": {"type": "snapshot", "tenant_id": "t-b"}}
	not authz.allow with input as {"actor": svc, "action": "config.agent.write", "resource": {"type": "agent"}}
	not authz.allow with input as {"actor": svc, "action": "conversation.all.read", "resource": {"type": "conversation"}}
}
