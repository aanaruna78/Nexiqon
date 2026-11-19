# ADR 0027: Single-node and air-gapped installs, offline licence, minimal footprint, cloud modules

Status: Accepted (2026-11-19)

## Context

Phase 4 slice 8 covers the remaining hosting options:

- **DV-05:** one server, with GPU models;
- **DV-06:** air-gapped installs with an offline licence;
- **DV-09:** the minimum on-premises footprint;
- **DV-03b:** infrastructure modules for AWS, Google Cloud and Azure.

All of them must keep the guarantees of the Kubernetes install: hardened containers, keys mounted
only where they are needed, and the same gateway behaviour.

## Decision

- **Single node (`deploy/single-node`)** is Docker Compose with a TLS front (Caddy):
  - Studio is served on 443, and the API and widget on 8443.
  - `install.sh` checks the server, writes `.env` with a new random password per component, writes
    settings that contain no secrets, initialises the database and OpenBao, starts everything, and
    waits for health. Running it again is safe.
  - **The gateway configuration is generated from the Helm chart** and committed. CI fails if
    the two differ, so both installs route, authorise and harden requests the same way.
  - **Keys** are made by `nexiqon-keys`, a new command in the platform image, inside a Docker
    volume. Each group mounts only its own files (Compose volume `subpath`), so the split from
    ADR 0026 holds on one server.
  - **OpenBao** uses file storage and unseals itself with a key kept in its own volume. This is
    stated plainly in the README: use disk encryption, or HSM or KMS auto-unseal. The tool
    gateway gets a token limited to the secrets mount.
  - `backup.sh` saves the database, files, keys and secret store.
  - **Proof:** a real install on a test machine reached every service healthy, served Studio and
    the API over TLS with the security headers, refused internal paths, kept the agent group
    away from the signing keys, and recovered OpenBao after a restart.
- **Air-gapped bundle** (`tools/bundle/build_bundle.py --airgap`) contains:
  - every image (`docker save`), the chart, model weights (`--gpu`), the licence verification
    keys, and `SHA256SUMS`.

  `install.sh --offline` refuses a bundle whose checksums differ, loads the images, never pulls
  (`--pull never`, `HF_HUB_OFFLINE=1`), and copies the weights. **Proof:** a 1.17 GB bundle,
  unpacked elsewhere with an image removed locally, installed and served; a changed file stopped
  the install.
- **Offline licence** (`nexiqon_core/licence.py`):
  - A compact JWS (ES256) is verified with the vendor's public key alone. The vendor keeps the
    private key offline and issues licences with `tools/licence/issue.py`.
  - Identity applies it:
    - an invalid licence, or a missing licence where one is required, stops identity at startup;
    - organizations beyond `max_tenants` are refused, using a count-only database policy set
      just for the check;
    - after expiry plus the grace period, staff sign-in is refused, but widgets and API keys
      keep answering, so a customer's own users are never cut off by a renewal delay;
    - administrators read the status at `GET /identity/v1/licence` (`admin_only`).
  - Tested in core and identity, and in a real install where a forged licence stopped identity.
- **Minimum footprint** (`values/minimal.yaml`):
  - The CPU node runs the platform at one replica each, with requests of 1.2 CPU and 2.5 GiB.
  - The GPU node runs the new optional `models` section: the three vLLM servers, with the names
    the on-prem model profiles expect and a shared weights volume.
  - There is no mesh, no bundled monitoring (OTLP to the customer's collector) and no LLM
    tracing tool.
  - Sizing and the dependencies' smallest settings: `docs/guides/minimal-footprint.md`.
- **Cloud modules:**
  - `deploy/tofu/modules/{aws,gcp,azure}` mirror the DigitalOcean module's outputs. They use
    managed PostgreSQL with pgvector, Valkey (Azure Managed Redis on Azure), object storage, and
    an optional labelled and tainted GPU pool.
  - Providers are pinned exactly, to releases more than two weeks old (aws 6.71.0, google
    8.9.0, azurerm 5.12.0); `tofu validate` runs in CI for all four.
  - **Azure Blob does not speak S3**, so a small `azure` blob adapter (Shared Key, no SDK) was
    added. It is tested against Azurite.

## Consequences and limits

- No cloud module has been applied to a real account yet: that needs credentials and the owner's
  go-ahead. The backlog asks for one non-DigitalOcean apply before the first customer there.
- The single-node install brings no identity provider; the customer's OIDC provider is required.
  Administrators need MFA reported in the token, or the setting must be turned off knowingly.
- The minimal profile has been rendered and schema-checked, not run on real GPU hardware.
- The bundled Helm dependencies (`bundled.*`) stay development-grade. Production installs use the
  dependencies' own charts or managed services.
- ClamAV signatures in an air-gapped install are as fresh as the last bundle.
