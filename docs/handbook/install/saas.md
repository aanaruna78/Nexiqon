# SaaS

There is nothing to install. Sign in to Studio, create your organization and follow the
[Quickstart](../quickstart.md).

- **Region.** Choose the region when the organization is created. Its documents, conversations and
  answers stay in that region's cell. Only sign-in and configuration are shared.
- **Your identity provider.** Sign in through your company's OpenID Connect provider.
  Administrators must use multi-factor authentication.
- **Your data.** Each organization is isolated in every store (row-level security, tenant-scoped
  keys and files), and every change is written to a tamper-evident audit log. You can export
  everything, set retention, and delete the organization from **Settings → Organization**.
- **Connecting your systems.** Tools call your APIs over HTTPS with credentials kept in the secret
  store. Give them the narrowest credentials that work, and keep the confirmation step for anything
  that changes data.

Need your data in your own cluster? See [Hybrid](hybrid.md).
