# Config schemas

`config/<kind>.schema.json` — JSON Schema 2020-12 for every configuration kind (Domain Pack, agent,
model profile, retrieval profile, tool, channel, tenant settings, security floors, retention profile).

* Source of truth: `services/config/src/nexiqon_config/schemas/` (shipped with the config service).
* Exported here by `make contracts`; CI fails if this copy is stale.
* `x-ui` keywords are hints for Studio's schema-driven forms (`widget`, `advanced`); validators ignore them.
* Served at runtime by `GET /config/v1/kinds`.
