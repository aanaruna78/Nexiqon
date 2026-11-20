# API reference

Everything Studio does is available over HTTPS. Every service is reached through the gateway, under
its own path: `https://<gateway>/<service>/v1/...`. The pages in this section list each service's
public endpoints. They are generated from the OpenAPI documents in `contracts/openapi/`, which are
the exact contracts the services are tested against.

## Authentication

Send a **server API key** as a bearer token:

```bash
curl https://<gateway>/conversation/v1/conversations \
  -H "Authorization: Bearer nxq_..." \
  -H "Content-Type: application/json" \
  -d '{"agent": "support", "channel": "api"}'
```

**Server keys** (Studio: **Settings → API keys**):

- Each key carries roles, which decide what it may do, exactly like a member's role.
- Keep server keys on servers only: they are passwords.

**Widget keys:**

- They are made for one assistant, on its **Widget** tab.
- They work only from the websites you listed (the browser's `Origin`), and only for that
  assistant.
- Each visitor gets their own conversations.

**Studio sessions** use your identity provider's token plus the `X-Nexiqon-Tenant` header, which
names the organization. Studio handles this for you; the browser never sees a token.

The gateway turns any of these into a short-lived signed context, which every service checks. Your
request can never name another organization's data.

## A conversation over the API

```bash
# 1. Start a conversation with an assistant
curl -X POST https://<gateway>/conversation/v1/conversations \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"agent": "support", "channel": "api"}'
# → {"id": "c1...", "status": "active", ...}

# 2. Ask a question; the reply carries the answer and its citations
curl -X POST https://<gateway>/conversation/v1/conversations/c1.../messages \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"content": "How do I invite a teammate?"}'
```

The reply's `contract` tells you what kind of answer it is:

- `grounded`, `smalltalk`, `declined`, `handoff`, `approval`, and so on;
- its `citations`;
- whether the assistant **abstained** (it could not back an answer with your sources).

### Streaming

`POST .../messages/stream` returns the same reply as **server-sent events**, as the assistant
writes it. The events are:

- `run`: the run started;
- `status`: the current stage (understanding, searching, writing);
- `sources`: the passages found;
- `tool`: a tool's progress;
- `delta`: the next piece of the answer text;
- `message`: the final, checked reply (the same body as the non-streaming call);
- `error`: the turn failed; `code` and `detail` say why.

Always show the final `message` event's text. It has been checked (citations verified, unsafe
content removed), so it can differ from the streamed deltas.

### Tools that change data

When the assistant wants to use a tool that changes data, the reply has `status:
awaiting_approval`. Nothing happens until you call `POST .../approval` with
`{"approved": true}` or `{"approved": false}`.

## Errors

Errors use one format (RFC 9457 problem details) in every service:

```json
{
  "type": "about:blank",
  "title": "Forbidden",
  "status": 403,
  "code": "forbidden",
  "detail": "You don't have permission to do that.",
  "instance": "/v1/conversations",
  "request_id": "bdfa240961a0466cb5d5e565ff9ef25b"
}
```

| Status | Code | Meaning |
|---|---|---|
| 400 | `bad_request` | The request is malformed |
| 401 | `unauthorized` | Missing, expired or unknown credentials |
| 403 | `forbidden` | Valid credentials, but not allowed (role, origin, licence) |
| 404 | `not_found` | It does not exist, or you may not see it |
| 409 | `conflict` | It clashes with the current state (a name already taken, a version already published) |
| 422 | `validation_failed` | A field is invalid; `errors` lists which and why |
| 429 | | Too many requests; retry after a short wait |

Quote the `request_id` when you contact support. It finds the request's trace.

## Services

| Service | Path | Reference |
|---|---|---|
| Conversations | `/conversation` | [Conversations](conversation.md) |
| Channels and the widget | `/channel` | [Channels](channel.md) |
| Assistant runs | `/agent-runtime` | [Assistant runs](agent-runtime.md) |
| Knowledge ingestion | `/ingestion` | [Ingestion](ingestion.md) |
| Search and citations | `/retrieval` | [Retrieval](retrieval.md) |
| Tools and actions | `/tool-gateway` | [Tools](tool-gateway.md) |
| Configuration | `/config` | [Configuration](config.md) |
| Identity | `/identity` | [Identity](identity.md) |
| Evaluations | `/evaluation` | [Evaluations](evaluation.md) |
| Usage, cost and insights | `/metering` | [Metering](metering.md) |
| Notifications and webhooks | `/notification` | [Notifications](notification.md) |
| Data export, retention and deletion | `/governance` | [Governance](governance.md) |
| Audit log | `/audit` | [Audit](audit.md) |

**Webhooks:** platform events are delivered to your endpoints, signed. The `X-Nexiqon-Signature`
header carries `t` (time) and `v1`, the HMAC-SHA256 of `"t.body"` with your endpoint's secret.
