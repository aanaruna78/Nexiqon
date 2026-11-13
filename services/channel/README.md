# channel

Channel adapters and their settings (CH-01, ADR 0020). Plane: **data**; runs in the `agent` group.

A channel turns a resolved agent into what one kind of client needs. Every channel then talks
through the same conversation endpoints, so streaming, citations, approvals and handoff behave the
same everywhere.

| Endpoint | Who | What |
|---|---|---|
| `GET /v1/channels` | `channel.settings.read` | channel types on offer (`widget`, `api`) |
| `GET /v1/channels/{channel}/agents/{agent}?locale=` | `channel.settings.read`; widget keys only for `widget` | widget: title, greeting, starter questions, accent colour (from the pack's `channels.widget`), whether handoff is offered, endpoints and stream events |

Agents are read with channel's own identity, `service:channel` (only `config.agent.read`), and
cached briefly. The full agent configuration is never returned. In the grouped topology this
service shares a process with agent-runtime, so its key goes under `channel_identity`
(`deploy/compose/config/dev-secrets-channel.yaml`, made by `make dev-secrets`).

New channels (Slack, Teams, email) implement the `Channel` protocol in `channels.py` and register in
`REGISTRY`.

```bash
uv run pytest services/channel
```
