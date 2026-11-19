# Nexiqon on one server

This is the whole platform on a single Linux server, with Docker Compose. Optionally, models run
on the server's own NVIDIA GPUs (DV-05). The same bundle installs with no network access at all
(air-gapped, DV-06). For more than one server, use the Helm chart (`deploy/helm/nexiqon`).

**Install time:** usually 15 to 30 minutes on a prepared server, plus image downloads (connected)
or loading the bundle (air-gapped).

## Requirements

| | Minimum (trial) | Recommended (production, up to about 50 staff and 20 answers a minute) |
|---|---|---|
| CPU | 4 cores | 8 cores |
| Memory | 16 GB | 32 GB |
| Disk | 60 GB SSD | 200 GB SSD, plus your documents |
| GPU (`--gpu`) | 1 × 24 GB (L4, A10, RTX 4090) | 1 × 48 GB (L40S) or 2 × 24 GB |
| OS | Linux x86_64 with Docker Engine 25+ and Compose 2.24+ | the same |
| GPU software | NVIDIA driver 550+, NVIDIA Container Toolkit | the same |

You also need:

- **An OpenID Connect identity provider** (Entra ID, Okta, Keycloak, ADFS and so on) with a
  client for Studio:
  - client id `nexiqon-studio`, or your own (`--oidc-client-id`);
  - redirect URI `https://<host>/auth/callback`;
  - PKCE enabled.

  Administrators must sign in with multi-factor authentication. The provider must report it in
  the token (`amr`), or set `NEXIQON_REQUIRE_ADMIN_MFA=false` in `.env` (not recommended).
- **A DNS name** for the server, and a TLS certificate for it (or use the built-in private CA; see
  below).
- **Ports open to users:** 443 (Studio) and 8443 (API and website widget).

## Install

```bash
tar xzf nexiqon-<version>.tar.gz && cd nexiqon-<version>/deploy/single-node
./install.sh --host ai.example.com --oidc-issuer https://login.example.com/realms/corp \
  --tls-cert /path/cert.pem --tls-key /path/key.pem
#   --gpu        self-hosted models on this server's GPUs (vLLM: chat, embeddings, reranking)
#   --licence    the licence file you received (required by licensed bundles)
```

`install.sh` does the following:

1. It checks the server (it stops if the server is below the minimum; `--force` turns that into
   a warning, for trials).
2. It writes `.env`, with a new random password for every component. `.env` is readable by you
   only.
3. It writes the settings and the TLS front.
4. It creates the installation's signing keys inside Docker (each service group gets only its own
   keys).
5. It initialises the database and the secret store, then starts everything and waits until it
   is healthy.

**Running it again is safe.** Passwords, keys and data are kept. Change `.env`, then run it
again to apply the change.

**The first sign-in.** The first person to sign in creates the organization and becomes its
owner. They can then invite colleagues from Studio.

**Without a certificate,** the TLS front issues one from its own private CA. Browsers will warn
until you trust that CA:

```bash
docker compose cp front:/data/caddy/pki/authorities/local/root.crt .
```

## Air-gapped install

Ask for the **air-gapped bundle**: `nexiqon-<version>-airgap.tar.gz`. It contains:

- every container image;
- the Helm chart;
- the model weights (GPU bundles);
- the licence verification keys;
- `SHA256SUMS`.

Bring it in by your approved transfer process, then:

```bash
tar xzf nexiqon-<version>-airgap.tar.gz && cd nexiqon-<version>-airgap/deploy/single-node
./install.sh --offline --gpu --licence /media/transfer/customer.licence \
  --host ai.corp.internal --oidc-issuer https://adfs.corp.internal/adfs --oidc-jwks-url https://adfs.corp.internal/adfs/discovery/keys
```

`--offline` does the following:

- checks every file against `SHA256SUMS`, and stops if anything differs;
- loads the images and copies the weights into the models volume;
- never contacts a registry or Hugging Face (`HF_HUB_OFFLINE=1`).

**Model profiles.** Assistants use the built-in `on-prem-small` and `on-prem-standard` model
profiles, which point at the local vLLM servers. Cloud profiles fail closed, because they have no
keys.

**Updates.** Bring in the next bundle and run `install.sh --offline` from it, with the same
`.env`. Copy `.env` and `config/licence.jws` across first. Virus signatures (ClamAV) are part of
each bundle's image, so update regularly.

## Licence

A licensed bundle verifies its licence **offline**, with the vendor's public key in the bundle:

- **Invalid or missing:** the platform does not start, and the reason is in
  `docker compose logs control-core`.
- **The last 30 days, then the grace period** (30 days by default): everything works, and
  administrators can see the status (`GET /identity/v1/licence`).
- **After the grace period:** staff can no longer sign in. Widgets and API keys keep answering,
  so your own users are never cut off by a renewal delay.
- **Organizations above the licensed number** cannot be created.

To renew, copy the new file to `config/licence.jws` and run `install.sh` again (or restart
`control-core`).

## Operations

| Task | Command |
|---|---|
| Status | `docker compose -p nexiqon --env-file .env ps` |
| Logs | `docker compose -p nexiqon --env-file .env logs -f <service>` |
| Back up | `./backup.sh`: database, files, keys and secret store, into `backups/<time>/`. Copy it off the server and keep it encrypted |
| Stop / start | `docker compose -p nexiqon --env-file .env stop` / `./install.sh` |
| Update | Unpack the new bundle next to this one, copy `.env` (and `config/licence.jws`), then run its `install.sh` |

**Restore** onto a new server:

1. Unpack the same version and copy `env` to `.env`.
2. Create the volumes with `./install.sh`, then stop everything.
3. Untar each `*.tar.gz` into its volume (`<project>_s3data`, `_keys`, `_baodata`).
4. Restore the database:

   ```bash
   docker compose exec -T postgres pg_restore -U nexiqon -d nexiqon --clean < nexiqon.dump
   ```
5. Run `./install.sh` again.

The timed restore drill is in `docs/runbooks/backup-restore.md`.

**Monitoring.** Set `NEXIQON_TELEMETRY_ENABLED=true` and `NEXIQON_OTLP_ENDPOINT` in `.env` to send
traces and metrics to your own OpenTelemetry collector. There is no bundled monitoring stack, to
keep the footprint small. The alert rules in `deploy/observability/prometheus-rules.yaml` work
with any Prometheus.

## Security notes

- Only ports 443 and 8443 (and 80, which redirects) are published. The database, queues and
  services are reachable on the internal Docker network only.
- Containers run as non-root, with read-only filesystems and no capabilities, and they cannot
  gain privileges.
- **Signing keys** are mounted file by file: only identity and config hold the token-signing
  private keys, and each service holds only its own identity key.
- **The secret store** (OpenBao) unseals itself with a key stored in its own volume, so it comes
  back after a reboot. That key sits on the same disk as the data, so a stolen disk is not
  protected by sealing; use full-disk encryption. With an HSM or cloud KMS, configure OpenBao
  auto-unseal instead. The tool gateway's token can use the secrets mount only.
- **Backups contain secrets** (keys, passwords): store them encrypted.
- This is one server: it has no high availability. Use the Helm chart for that.
