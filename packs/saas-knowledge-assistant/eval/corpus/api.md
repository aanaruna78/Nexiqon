# API Reference

## Authentication

Create an API token in Settings, Developer, API tokens. Send it in the Authorization header as a Bearer token.
Tokens inherit the permissions of the member who created them and can be revoked at any time.

## Rate limits

The API allows 600 requests per minute per token. When you exceed the limit you receive HTTP 429 with a Retry-After header.
Bulk endpoints count each item as one request.

## Webhooks

Webhooks send an HTTP POST to your URL when projects, files or members change. Each delivery is signed with HMAC SHA-256
using your webhook secret in the X-Acme-Signature header. Failed deliveries are retried for up to 24 hours.

## Pagination

List endpoints return 50 items per page. Use the cursor value from the response to fetch the next page.
