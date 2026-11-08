# Security and Single Sign-On

## Single sign-on (SSO)

Enterprise workspaces can use SAML 2.0 or OpenID Connect single sign-on with Okta, Microsoft Entra ID or Google Workspace.
To set up SSO, open Settings, Security, Single sign-on and upload your identity provider metadata.

### Enforce SSO

After testing the connection, turn on Enforce SSO so that members must sign in through your identity provider.
Owners keep a password login as a recovery option.

## Two-factor authentication

Members can protect their account with an authenticator app. Admins can require two-factor authentication for everyone.
Recovery codes are shown once when two-factor authentication is turned on; store them safely.

## Data encryption

All data is encrypted in transit with TLS 1.2 or later and at rest with AES-256. Encryption keys are rotated every 90 days.
