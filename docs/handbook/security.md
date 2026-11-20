# Security

**Isolation between organizations.**

- Every table holding customer data enforces row-level security for the application's database
  role.
- Files, caches, search indexes and workflows are keyed by organization.
- A service accepts a request only with a short-lived, signed context issued by the identity
  service at the gateway. Clients cannot forge or replace it.
- Automated isolation tests run in every service on every change.

**Access inside an organization.**

- Roles are owner, admin, editor and member.
- A deny-by-default policy is enforced in every service.
- Collections can be limited to access groups. Search applies those rules **before** ranking, so
  hidden content never influences an answer.
- **Access preview** shows exactly what a person or website visitor can retrieve.

**Where your data goes.**

- Each answer is labelled with the most sensitive source it used. Only model profiles allowed for
  that label may see it; nothing is rerouted silently.
- Personal data can be hidden from cloud models.
- Restricted data never goes to a cloud profile.

**Answers you can check.**

- Every claim cites a source, and citations are verified against the text.
- When the evidence is weak, the assistant says it does not know.
- Text in documents and tool results is treated as data, never as instructions. Lines that look
  like instructions are removed before the model sees them.

**Tools.**

- Tools run with the caller's permissions.
- Anything that changes data asks the user first.
- Credentials live in a secret store and are never shown to models or people.
- Outbound requests cannot reach private or internal addresses.

**Accountability.**

- Every change is written to a hash-chained audit log, which you can verify from Studio.
- Deleting an organization removes its data from every service after a grace period, and leaves a
  certificate of what was deleted.

**Operations.**

- Logs mask personal data and secrets.
- Containers run as non-root, with read-only filesystems, no added capabilities and no setuid
  binaries. Images are scanned for known vulnerabilities on every build.
- Default-deny network policies block the cloud metadata address.

To report a vulnerability, contact the Nexiqon security team through your support channel. Please
do not open a public issue.
