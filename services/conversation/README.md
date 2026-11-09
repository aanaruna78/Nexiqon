# conversation

Conversations between people and assistants. Plane: **data**; runs in the `agent` group.

| Endpoint | Who |
|---|---|
| `POST /v1/conversations` | anyone allowed to message (`conversation.messages.create`) |
| `POST /v1/conversations/{id}/messages` | the conversation's owner. The reply carries the answer contract: text, verified citations, abstained, kind, intent, route, run id |
| `POST /v1/conversations/{id}/approval {approved}` | owner, when an action waits for confirmation |
| `GET /v1/conversations[/{id}]` | owners see their own; staff (members and up) see all |
| `POST /v1/messages/{id}/feedback` | owner, on assistant messages |

Statuses: `active`, `awaiting_input` (clarifying question), `awaiting_approval`, `escalated`. When a
conversation is escalated, a person has it: messages are stored and the assistant stays quiet.
**Retention**: `retain_until` comes from the agent's retention profile (`conversations_days`) and is
extended on activity. An hourly sweep deletes expired conversations through an RLS policy that can
only see expired rows. Events: `turn.completed`, `escalated`, `feedback.given`.
