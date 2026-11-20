# Air-gapped

Nexiqon installs and runs with no internet access at all. There are two ways:

- **One server:** the air-gapped bundle and `install.sh --offline`. See
  [Single node → Air-gapped install](single-node.md#air-gapped-install).
- **Kubernetes:**
    1. Load the bundle's images into your registry (`images/*.tar`, with `docker load`, then push).
    2. Set `image.repository` and `studio.image.repository` to your registry.
    3. Set `models.offline: true`, and preload the model weights into the `models-cache` volume
       from the bundle's `models/` directory.

**The bundle is checked before anything is installed.** Every file is listed in `SHA256SUMS`, and
a damaged or altered bundle is refused.

**The licence is verified offline,** with the vendor's public key shipped in the bundle. Nothing
calls home. See [Single node → Licence](single-node.md#licence) for what happens at expiry; in
short, your users' widgets and API keys keep working.

**What you give up offline:**

- Cloud model profiles: they fail closed without keys.
- Automatic virus-signature updates: each bundle carries current signatures, so update regularly.
